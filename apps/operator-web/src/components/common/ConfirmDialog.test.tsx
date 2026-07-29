import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useConfirm } from "./useConfirm";

function Harness({ onResult }: { onResult: (confirmed: boolean) => void }) {
  const [requestConfirm, confirmDialog] = useConfirm();
  return (
    <div>
      <button
        onClick={async () => {
          onResult(await requestConfirm({
            title: "Home gantry",
            message: "Really go home?",
            confirmLabel: "Go",
          }));
        }}
      >
        Trigger
      </button>
      {confirmDialog}
    </div>
  );
}

describe("useConfirm", () => {
  it("resolves true when the user confirms", async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    render(<Harness onResult={onResult} />);

    await user.click(screen.getByRole("button", { name: "Trigger" }));
    const dialog = screen.getByRole("alertdialog", { name: "Home gantry" });
    expect(dialog).toHaveTextContent("Really go home?");

    await user.click(screen.getByRole("button", { name: "Go" }));

    expect(onResult).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("resolves false when the user cancels", async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    render(<Harness onResult={onResult} />);

    await user.click(screen.getByRole("button", { name: "Trigger" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onResult).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("resolves false on Escape", async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    render(<Harness onResult={onResult} />);

    await user.click(screen.getByRole("button", { name: "Trigger" }));
    // The confirm button receives focus on open, so Escape lands inside
    // the dialog.
    await user.keyboard("{Escape}");

    expect(onResult).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("focuses the confirm button on open", async () => {
    const user = userEvent.setup();
    render(<Harness onResult={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Trigger" }));

    expect(screen.getByRole("button", { name: "Go" })).toHaveFocus();
  });
});
