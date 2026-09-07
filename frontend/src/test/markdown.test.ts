import { describe, expect, it } from "vitest";
import { toHtml } from "@/components/ui/markdown";

/**
 * The install guide is server-rendered markdown, and its fenced blocks are the commands a person is
 * meant to run. They had no way to be taken: one button copied the whole document, so the single
 * line that mattered had to be selected by hand.
 *
 * The button is built into an HTML string rather than as a React element, which is exactly the kind
 * of code that goes subtly wrong — an unbalanced wrapper swallows the rest of the page.
 */
describe("toHtml", () => {
  const fenced = "Before\n\n```bash\nautoskill install --version-id v1 --target hermes\n```\n\nAfter";

  it("gives every fenced block its own copy button", () => {
    const html = toHtml(fenced, "Copy");
    expect(html).toContain("data-copy");
    expect((html.match(/data-copy/g) ?? []).length).toBe(1);
    // the button sits beside the block it copies, so a click can find the code from itself
    expect(html.indexOf("data-copy")).toBeLessThan(html.indexOf("<pre"));
  });

  it("closes every wrapper it opens, including an unterminated fence", () => {
    for (const source of [fenced, "```bash\nautoskill doctor\n"]) {
      const html = toHtml(source, "Copy");
      expect((html.match(/<div class="relative group">/g) ?? []).length).toBe(
        (html.match(/<\/div>/g) ?? []).length,
      );
      expect((html.match(/<pre/g) ?? []).length).toBe((html.match(/<\/pre>/g) ?? []).length);
    }
  });

  it("keeps the command intact, escaping only what would become markup", () => {
    const html = toHtml('```bash\necho "a" && b > c\n```', "Copy");
    expect(html).toContain('echo "a" &amp;&amp; b &gt; c');
  });

  it("uses the label it is given, so the button is translated", () => {
    expect(toHtml(fenced, "Copia")).toContain('aria-label="Copia"');
  });

  it("a quote in the label cannot break out of the attribute", () => {
    expect(toHtml(fenced, 'Cop"y')).toContain('aria-label="Cop&quot;y"');
  });
});
