export {};

declare global {
  interface Window {
    pywebview?: {
      api?: {
        minimize_window?: () => Promise<void>;
        toggle_maximize?: () => Promise<void>;
        close_window?: () => Promise<void>;
        select_project_folder?: (current?: string) => Promise<string>;
      };
    };
  }
}
