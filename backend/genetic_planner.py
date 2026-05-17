"""
Генетический планировщик (без внешних библиотек ГА): та же постановка, что у жадного.

**Кодирование:** перестановка индексов базового списка заказов, пересекающихся с периодом
(``eligible``), в порядке ``sorted(eligible, key=id)`` — однозначное соответствие хромосоме.

**Декодирование и ограничения:** ``schedule_eligible_orders_in_sequence`` из ``planner.py`` —
те же слоты, календарь, активное оборудование, откат при неразмещении заказа («всё или ничё»).

**Фитнес:** сумма ``profit`` по полностью включённым заказам (как ``total_profit_of_included_orders``).

Параметры читаются из окружения (дефолты для быстрого MVP на демо-данных):

- ``GENETIC_POP_SIZE`` (по умолчанию 24)
- ``GENETIC_GENERATIONS`` (по умолчанию 32)
- ``GENETIC_CROSSOVER_PROB`` (0.9)
- ``GENETIC_MUTATION_PROB`` (0.2)
- ``GENETIC_SEED`` (42) — обязателен для воспроизводимости; без явной установки используется 42.

При большом числе eligible-заказов время растёт линейно по числу оценок фитнеса; предупреждение
``SCHEDULE_GENETIC_LARGE_INPUT`` добавляется в роутере (см. ``GENETIC_ELIGIBLE_WARN_THRESHOLD``).
"""
from __future__ import annotations

import os
import random
from decimal import Decimal

from backend.models import Equipment, Order, Worker
from backend.planner import (
    PlannedOperation,
    PlannerExclusion,
    order_sort_key_for_planner,
    partition_orders_by_period_window,
    schedule_eligible_orders_in_sequence,
    total_profit_of_included_orders,
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


DEFAULT_POP_SIZE = 24
DEFAULT_GENERATIONS = 32
DEFAULT_CROSSOVER_PROB = 0.9
DEFAULT_MUTATION_PROB = 0.2
DEFAULT_SEED = 42


def _one_point_perm_crossover(rng: random.Random, p1: list[int], p2: list[int]) -> tuple[list[int], list[int]]:
    n = len(p1)
    if n <= 1:
        return p1[:], p2[:]
    pt = rng.randint(1, n - 1)

    def child(first: list[int], second: list[int]) -> list[int]:
        head = first[:pt]
        tail = [x for x in second if x not in head]
        return head + tail

    return child(p1, p2), child(p2, p1)


def _mutate_swap(rng: random.Random, chrom: list[int], prob: float) -> None:
    if rng.random() >= prob:
        return
    n = len(chrom)
    if n < 2:
        return
    i, j = rng.sample(range(n), 2)
    chrom[i], chrom[j] = chrom[j], chrom[i]


def _tournament_pick(rng: random.Random, pop: list[list[int]], fitness: list[Decimal], k: int) -> list[int]:
    best = rng.randrange(len(pop))
    best_f = fitness[best]
    for _ in range(k - 1):
        cand = rng.randrange(len(pop))
        if fitness[cand] > best_f:
            best = cand
            best_f = fitness[cand]
    return pop[best][:]


def genetic_planner(
    orders: list[Order],
    workers: list[Worker],
    equipment: list[Equipment],
    period_start,
    period_end,
) -> tuple[list[PlannedOperation], list[PlannerExclusion]]:
    """
    Подбор порядка заказов генетическим алгоритмом; размещение операций — общее с жадным планировщиком.

    Возвращает тот же тип, что ``greedy_planner``: запланированные операции и объединённые исключения
    (вне периода + не поместившиеся / ресурсы).
    """
    pop_size = max(2, _env_int("GENETIC_POP_SIZE", DEFAULT_POP_SIZE))
    generations = max(1, _env_int("GENETIC_GENERATIONS", DEFAULT_GENERATIONS))
    cx_prob = _env_float("GENETIC_CROSSOVER_PROB", DEFAULT_CROSSOVER_PROB)
    mut_prob = _env_float("GENETIC_MUTATION_PROB", DEFAULT_MUTATION_PROB)
    seed = _env_int("GENETIC_SEED", DEFAULT_SEED)
    rng = random.Random(seed)

    sorted_orders = sorted(orders, key=order_sort_key_for_planner)
    eligible, outside_excl = partition_orders_by_period_window(sorted_orders, period_start, period_end)
    if not eligible:
        return [], outside_excl

    base = sorted(eligible, key=lambda o: o.id)
    n = len(base)
    identity = list(range(n))
    orders_by_id = {o.id: o for o in orders}

    def evaluate(perm: list[int]) -> tuple[Decimal, list[PlannedOperation], list[PlannerExclusion]]:
        seq = [base[i] for i in perm]
        planned, inc_excl = schedule_eligible_orders_in_sequence(
            seq, workers, equipment, period_start, period_end
        )
        fit = total_profit_of_included_orders(planned, orders_by_id)
        return fit, planned, inc_excl

    def random_perm() -> list[int]:
        p = identity[:]
        rng.shuffle(p)
        return p

    # Жадный порядок в индексах базы (прибыль ↓, id ↑)
    greedy_seq = sorted(base, key=order_sort_key_for_planner)
    greedy_perm = [base.index(o) for o in greedy_seq]

    population: list[list[int]] = [greedy_perm, identity[:], random_perm()]
    while len(population) < pop_size:
        population.append(random_perm())

    best_perm = greedy_perm[:]
    best_fit, best_planned, best_inc_excl = evaluate(best_perm)

    for _gen in range(generations):
        fitness: list[Decimal] = []
        for ind in population:
            fit, pl, ex = evaluate(ind)
            fitness.append(fit)
            if fit > best_fit or (fit == best_fit and tuple(ind) < tuple(best_perm)):
                best_fit = fit
                best_perm = ind[:]
                best_planned = pl
                best_inc_excl = ex

        new_pop: list[list[int]] = [best_perm[:]]
        while len(new_pop) < pop_size:
            p1 = _tournament_pick(rng, population, fitness, 3)
            if rng.random() < cx_prob:
                p2 = _tournament_pick(rng, population, fitness, 3)
                c1, c2 = _one_point_perm_crossover(rng, p1, p2)
                _mutate_swap(rng, c1, mut_prob)
                _mutate_swap(rng, c2, mut_prob)
                new_pop.append(c1)
                if len(new_pop) < pop_size:
                    new_pop.append(c2)
            else:
                c = p1[:]
                _mutate_swap(rng, c, mut_prob)
                new_pop.append(c)
        population = new_pop

    # Финальный проход лучшей особи (на случай дрейфа последней популяции)
    best_fit, best_planned, best_inc_excl = evaluate(best_perm)
    return best_planned, outside_excl + best_inc_excl
