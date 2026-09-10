// scoring an item against a reader's ranked requirements.

import type { Item, Topic } from "./types";

// the top ranked requirement is worth this much and each rank below it
// proportionally less, so relative order matters more than list length.
const TOP_WEIGHT = 100;

// a forced anti-requirement counts double against anything that has it.
const FORCED_PENALTY = 2;

export interface Ranking {
  // requirement indexes, most important first
  required: number[];
  excluded: number[];
  forced: ReadonlySet<number>;
}

export interface Scored {
  item: Item;
  total: number;
  // set when a forced requirement rules the item out entirely
  filtered: boolean;
}

function weight(rank: number): number {
  return TOP_WEIGHT / (rank + 1);
}

function scoreOf(item: Item, requirement: number): number {
  return item.evaluations[requirement]?.score ?? 0;
}

export function scoreItem(item: Item, ranking: Ranking): Scored {
  let total = 0;
  let filtered = false;

  ranking.required.forEach((requirement, rank) => {
    const score = scoreOf(item, requirement);
    const value = weight(rank);
    if (ranking.forced.has(requirement) && score !== 1) {
      filtered = true;
      total += Math.trunc(value * score - value);
    } else {
      total += Math.trunc(value * score);
    }
  });

  ranking.excluded.forEach((requirement, rank) => {
    const score = scoreOf(item, requirement);
    let value = weight(rank);
    if (ranking.forced.has(requirement) && score !== 0) {
      filtered = true;
      value *= FORCED_PENALTY;
    }
    total += Math.trunc(value * -score);
  });

  return { item, total, filtered };
}

// every item scored and sorted, the best match first.
export function rankItems(topic: Topic, ranking: Ranking): Scored[] {
  return topic.items
    .map((item) => scoreItem(item, ranking))
    .sort((a, b) => b.total - a.total);
}
