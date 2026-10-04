export {};

declare global {
  interface Window {
    pywebview?: {
      api?: {
        select_project_folder?: (current?: string) => Promise<string>;
      };
    };
  }
}
