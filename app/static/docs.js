"use strict";

// Swagger's summary button contains a link. Keep permalinks beside the button.
function ModelLabDocsPlugin(system) {
  const React = system.React;
  return {
    wrapComponents: {
      OperationSummaryPath: () => ({ operationProps }) => React.createElement(
        "span", { className: "opblock-summary-path", "data-path": operationProps.get("path") },
        operationProps.get("path"),
      ),
      OperationSummary: (Original) => class extends Original {
        render() {
          const element = super.render();
          const { tag, operationId, method, path } = this.props.operationProps.toObject();
          const link = React.createElement("a", {
            className: "operation-permalink", key: "permalink",
            href: `#/${encodeURIComponent(tag)}/${encodeURIComponent(operationId)}`,
            "aria-label": `Link to ${method.toUpperCase()} ${path}`,
          }, "Link");
          return React.cloneElement(element, {}, ...React.Children.toArray(element.props.children), link);
        }
      },
    },
  };
}

// Swagger inserts cURL samples after execution; keyboard users must be able to scroll them.
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("swagger-ui");
  if (!root) return;
  const labelSamples = () => {
    for (const sample of root.querySelectorAll(".curl")) {
      sample.tabIndex = 0;
      sample.setAttribute("role", "region");
      sample.setAttribute("aria-label", "cURL request sample");
    }
  };
  labelSamples();
  new MutationObserver(labelSamples).observe(root, { childList: true, subtree: true });
});
