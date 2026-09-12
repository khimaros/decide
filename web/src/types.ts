// the shape the generator publishes as topic.json. keep in sync with the
// serde types in src/topics.rs.

export interface Evaluation {
  score: number;
  comment: string;
  // where the score came from, in any form, empty when nothing was cited.
  sources: string[];
}

export interface Requirement {
  name: string;
  // ascending importance, negative for anti-requirements, null when the
  // reader is expected to rank it themselves.
  priority: number | null;
  force: boolean;
}

export interface Item {
  name: string;
  // one entry per requirement, in requirement order, null where the topic
  // says nothing about that requirement.
  evaluations: (Evaluation | null)[];
}

export interface Topic {
  slug: string;
  name: string;
  requirements: Requirement[];
  items: Item[];
}
