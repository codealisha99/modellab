"use strict";
(() => {
  const tokens = getComputedStyle(document.documentElement);
  const token = (name) => tokens.getPropertyValue(`--${name}`).trim();
  Redoc.init("/openapi.json", {
    theme: {
      colors: {
        primary: { main: token("brand") },
        text: { primary: token("text"), secondary: token("text-secondary") },
        success: { main: token("success") },
        error: { main: token("error") },
        http: { get: token("info"), post: token("success"), delete: token("error") },
      },
      typography: {
        fontFamily: token("font-sans"), fontSize: "14px", lineHeight: "1.65",
        headings: { fontFamily: token("font-sans"), fontWeight: "650" },
        code: { fontFamily: token("font-mono") },
      },
      sidebar: { backgroundColor: token("surface-muted"), textColor: token("text"), activeTextColor: token("brand-active") },
      rightPanel: { backgroundColor: token("terminal"), textColor: token("terminal-text") },
    },
  }, document.getElementById("redoc"));
})();
