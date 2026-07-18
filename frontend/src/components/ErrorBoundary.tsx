import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean; message: string | null };

/**
 * Catches render-time errors anywhere in the tree so a single broken page
 * shows a graceful fallback instead of a blank white screen. Without this,
 * an uncaught error in a lazily-loaded route unmounts the whole app.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: null };

  static getDerivedStateFromError(error: unknown): State {
    const message = error instanceof Error ? error.message : "Unexpected error";
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // Surface in the console for local debugging / error-tracking hooks.
    console.error("Unhandled UI error:", error, info.componentStack);
  }

  private handleReload = (): void => {
    this.setState({ hasError: false, message: null });
    window.location.assign("/");
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    return (
      <div
        role="alert"
        className="grid min-h-screen place-items-center bg-[#050e09] px-6 text-center"
      >
        <div className="max-w-md">
          <p className="font-display text-2xl font-semibold tracking-tight text-[#C5A059]">
            Something went wrong
          </p>
          <p className="mt-3 font-sans text-sm text-zinc-400">
            The page hit an unexpected error. Your session is safe — try reloading.
          </p>
          {this.state.message && (
            <p className="mt-2 break-words font-mono text-xs text-zinc-600">
              {this.state.message}
            </p>
          )}
          <button
            type="button"
            onClick={this.handleReload}
            className="mt-6 rounded-none bg-[#C5A059] px-4 py-2 font-semibold tracking-wide text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a]"
          >
            Reload the app
          </button>
        </div>
      </div>
    );
  }
}
