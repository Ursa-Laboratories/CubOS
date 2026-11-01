import { useRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ConfigDirDialog } from "../../../../src/components/common/ConfigDirDialog";
import { ConfirmDialog } from "../../../../src/components/common/ConfirmDialog";

function Harness() {
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  return <>
    <button ref={trigger} onClick={() => setOpen(true)}>Browse</button>
    {open && <ConfigDirDialog initialPath="/configs" error={null}
      returnFocus={trigger} onSubmit={() => setConfirm(true)} onCancel={() => setOpen(false)} />}
    {confirm && <ConfirmDialog title="Discard changes?" message="Discard local edits?"
      onConfirm={() => { setConfirm(false); setOpen(false); }} onCancel={() => setConfirm(false)} />}
  </>;
}

describe("dialog focus", () => {
  it("skips disabled submission and restores the trigger after Escape", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Browse" }));
    const input = screen.getByRole("textbox");
    await user.clear(input);
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.tab();
    expect(input).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Browse" })).toHaveFocus();
  });

  it("keeps nested confirmation focus separate and restores the parent control", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Browse" }));
    await user.click(screen.getByRole("button", { name: "Use Directory" }));
    const dialog = screen.getByRole("alertdialog");
    await user.tab();
    expect(dialog.querySelector("button")).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use Directory" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("textbox")).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Browse" })).toHaveFocus();
  });
});
