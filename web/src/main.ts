// loads a topic and wires it up to the sortable requirement lists.

import Sortable from "sortablejs";

import { rankItems, type Ranking, type Scored } from "./score";
import type { Item, Requirement, Topic } from "./types";

// score at or above which a requirement is considered met, and below which
// it is considered unmet. anything between the two is a partial match.
const GOOD = 0.7;
const FAIR = 0.3;

// bootstrap icons, MIT licensed.
const HANDLE_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M7 2a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm3 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0zM7 5a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm3 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0zM7 8a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm3 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm-3 3a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm3 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm-3 3a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm3 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0z"/></svg>';

const FORCE_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M2 2a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v13.5a.5.5 0 0 1-.777.416L8 13.101l-5.223 2.815A.5.5 0 0 1 2 15.5V2zm2-1a1 1 0 0 0-1 1v12.566l4.723-2.482a.5.5 0 0 1 .554 0L13 14.566V2a1 1 0 0 0-1-1H4z"/><path d="M8 4a.5.5 0 0 1 .5.5V6H10a.5.5 0 0 1 0 1H8.5v1.5a.5.5 0 0 1-1 0V7H6a.5.5 0 0 1 0-1h1.5V4.5A.5.5 0 0 1 8 4z"/></svg>';

const FORCE_ICON_ON =
  '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path fill-rule="evenodd" d="M2 15.5V2a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v13.5a.5.5 0 0 1-.74.439L8 13.069l-5.26 2.87A.5.5 0 0 1 2 15.5zm6.5-11a.5.5 0 0 0-1 0V6H6a.5.5 0 0 0 0 1h1.5v1.5a.5.5 0 0 0 1 0V7H10a.5.5 0 0 0 0-1H8.5V4.5z"/></svg>';

let topic: Topic;
let required: HTMLElement;
let excluded: HTMLElement;
let itemList: HTMLElement;
let sortable: HTMLElement[] = [];

// remembered across redraws so an open item stays open while ranking changes
const expanded = new Set<string>();

function byId(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`missing element #${id}`);
  return element;
}

// the page names its data file rather than carrying the data itself, so the
// url stays relative to the page and works from any base path.
async function readTopic(): Promise<Topic> {
  const source = document.querySelector<HTMLMetaElement>('meta[name="topic-data"]');
  if (!source?.content) throw new Error("page does not name a topic data file");
  const response = await fetch(source.content);
  if (!response.ok) {
    throw new Error(`${source.content}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as Topic;
}

function reportFailure(list: HTMLElement, error: unknown): void {
  const li = document.createElement("li");
  li.className = "list-item";
  li.textContent = `could not load this topic: ${error instanceof Error ? error.message : error}`;
  list.replaceChildren(li);
}

// requirements start out ranked by the priority the topic gave them.
function bucketOf(requirement: Requirement, ignored: HTMLElement): HTMLElement {
  if (requirement.priority === null) return ignored;
  return requirement.priority < 0 ? excluded : required;
}

function requirementIndexes(list: HTMLElement): number[] {
  return Array.from(list.children, (child) =>
    Number((child as HTMLElement).dataset.requirement),
  );
}

function forcedRequirements(): Set<number> {
  const pressed = document.querySelectorAll<HTMLElement>('.force[aria-pressed="true"]');
  return new Set(
    Array.from(pressed, (button) =>
      Number(button.parentElement?.dataset.requirement),
    ),
  );
}

function setForced(button: HTMLElement, on: boolean): void {
  button.setAttribute("aria-pressed", String(on));
  button.innerHTML = on ? FORCE_ICON_ON : FORCE_ICON;
}

function requirementElement(requirement: Requirement, index: number): HTMLLIElement {
  const li = document.createElement("li");
  li.className = "list-item";
  li.dataset.requirement = String(index);

  const handle = document.createElement("span");
  handle.className = "handle";
  handle.innerHTML = HANDLE_ICON;

  const force = document.createElement("button");
  force.type = "button";
  force.className = "force";
  force.title = "insist on this requirement";
  setForced(force, requirement.force);
  force.addEventListener("click", () => {
    setForced(force, force.getAttribute("aria-pressed") !== "true");
    update();
  });

  li.append(handle, requirement.name, force);
  return li;
}

function toneOf(score: number | undefined, anti: boolean): string {
  if (score === undefined) return "score-unknown";
  const met = anti ? 1 - score : score;
  if (met > GOOD) return "score-good";
  if (met > FAIR) return "score-fair";
  return "score-poor";
}

function detailRow(item: Item, index: number, anti: boolean): HTMLDivElement {
  const evaluation = item.evaluations[index] ?? undefined;
  const row = document.createElement("div");
  row.className = `detail-row ${toneOf(evaluation?.score, anti)}`;
  row.append(topic.requirements[index]?.name ?? "");

  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = evaluation ? evaluation.score.toFixed(1) : "???";
  row.append(badge);

  if (evaluation?.comment) {
    const comment = document.createElement("p");
    comment.className = "detail-comment";
    comment.textContent = evaluation.comment;
    row.append(comment);
  }
  return row;
}

function detailElement(scored: Scored, ranking: Ranking): HTMLDivElement {
  const detail = document.createElement("div");
  detail.className = "detail";
  detail.hidden = !expanded.has(scored.item.name);
  detail.addEventListener("click", (event) => event.stopPropagation());

  for (const index of ranking.required) {
    detail.append(detailRow(scored.item, index, false));
  }
  for (const index of ranking.excluded) {
    detail.append(detailRow(scored.item, index, true));
  }
  return detail;
}

function itemElement(scored: Scored, ranking: Ranking): HTMLLIElement {
  const li = document.createElement("li");
  li.className = scored.filtered ? "list-item item filtered" : "list-item item";

  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = String(scored.total);

  const detail = detailElement(scored, ranking);
  li.append(scored.item.name, badge, detail);

  li.addEventListener("click", () => {
    const open = !expanded.has(scored.item.name);
    if (open) expanded.add(scored.item.name);
    else expanded.delete(scored.item.name);
    detail.hidden = !open;
  });
  return li;
}

// moving a requirement between lists changes two cards' heights, and a
// multi-column container answers any height change by repacking every card, so
// sections jump columns while the pointer is still down. give every list room
// for one more row as the drag begins: the list the row left keeps its height,
// and the list it lands in already had the space waiting.
function reserveRoom(dragged: HTMLElement): void {
  const room = dragged.getBoundingClientRect().height;
  for (const list of sortable) {
    list.style.minHeight = `${list.getBoundingClientRect().height + room}px`;
    // the stylesheet draws the held space, and needs to know how tall it is.
    list.style.setProperty("--room", `${room}px`);
  }
  document.body.classList.add("dragging");
}

function releaseRoom(): void {
  for (const list of sortable) {
    list.style.minHeight = "";
    list.style.removeProperty("--room");
  }
  document.body.classList.remove("dragging");
}

// rescore every item against the current ranking and redraw the results.
function update(): void {
  const ranking: Ranking = {
    required: requirementIndexes(required),
    excluded: requirementIndexes(excluded),
    forced: forcedRequirements(),
  };
  const scored = rankItems(topic, ranking);
  itemList.replaceChildren(...scored.map((entry) => itemElement(entry, ranking)));
}

async function main(): Promise<void> {
  required = byId("requirements");
  excluded = byId("antirequirements");
  itemList = byId("items");
  const ignored = byId("nonrequirements");

  topic = await readTopic();

  topic.requirements.forEach((requirement, index) => {
    bucketOf(requirement, ignored).append(requirementElement(requirement, index));
  });

  sortable = [required, ignored, excluded];
  for (const list of sortable) {
    Sortable.create(list, {
      group: "requirements",
      handle: ".handle",
      animation: 150,
      ghostClass: "sortable-ghost",
      // drive the drag ourselves rather than through html5 drag and drop, which
      // browsers implement inconsistently and which ignores touch entirely.
      forceFallback: true,
      onStart: (event) => reserveRoom(event.item),
      // redraw while the room is still held, so the layout settles once.
      onEnd: () => {
        update();
        releaseRoom();
      },
    });
  }

  update();
}

main().catch((error) => reportFailure(itemList ?? document.body, error));
