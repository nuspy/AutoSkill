import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "@/i18n";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";
import { ApiError } from "@/api/client";
import i18n from "@/i18n";

describe("ui primitives", () => {
  it("renders a button with loading state", () => {
    render(<Button loading>Save</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });
  it("renders an empty state", () => {
    render(<EmptyState title="Nothing" description="desc" />);
    expect(screen.getByText("Nothing")).toBeInTheDocument();
  });
});

describe("error messages", () => {
  it("translates known API error codes", async () => {
    await i18n.changeLanguage("en");
    const err = new ApiError(401, { error: { code: "invalid_credentials", message: "x" } });
    expect(errorMessage(err, i18n.t)).toMatch(/incorrect/);
    const it = new ApiError(403, { error: { code: "unknown_code", message: "x" } });
    expect(errorMessage(it, i18n.t)).toMatch(/permission/);
  });
});
