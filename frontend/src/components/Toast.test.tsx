import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { Toast } from "./Toast";

describe("Toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when toast is null", () => {
    const { container } = render(<Toast toast={null} onDismiss={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the message with a polite live region", () => {
    render(<Toast toast={{ kind: "info", message: "Saved" }} onDismiss={() => {}} />);
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("Saved");
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("auto-dismisses after the timeout elapses", () => {
    const onDismiss = vi.fn();
    render(
      <Toast toast={{ kind: "success", message: "Done" }} onDismiss={onDismiss} autoHideMs={1000} />,
    );
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("dismisses when the close button is clicked", () => {
    const onDismiss = vi.fn();
    render(<Toast toast={{ kind: "error", message: "Nope" }} onDismiss={onDismiss} />);
    screen.getByLabelText("Dismiss").click();
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
