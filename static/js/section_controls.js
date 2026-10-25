(() => {
  document.querySelectorAll(".card[data-collapsible]").forEach((card, index) => {
    const title = Array.from(card.children).find((child) => /^H[1-6]$/.test(child.tagName));
    if (!title) return;

    const panel = document.createElement("div");
    panel.className = "card-section-content";
    panel.id = `card-section-content-${index + 1}`;
    while (title.nextSibling) panel.appendChild(title.nextSibling);

    const heading = document.createElement("div");
    heading.className = "card-section-heading";
    card.insertBefore(heading, title);
    heading.append(title);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "card-section-toggle";
    button.setAttribute("aria-controls", panel.id);
    const initiallyExpanded = card.dataset.startCollapsed !== "true";
    button.setAttribute("aria-expanded", initiallyExpanded ? "true" : "false");
    button.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="m5.5 7.5 4.5 4.5 4.5-4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const sectionTitle = title.textContent.trim();
    const initialAction = initiallyExpanded ? "Collapse" : "Expand";
    button.setAttribute("aria-label", `${initialAction} ${sectionTitle}`);
    button.title = `${initialAction} ${sectionTitle}`;
    heading.append(button);
    panel.hidden = !initiallyExpanded;
    card.append(panel);

    button.addEventListener("click", () => {
      const expanded = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", expanded ? "false" : "true");
      const action = expanded ? "Expand" : "Collapse";
      button.setAttribute("aria-label", `${action} ${sectionTitle}`);
      button.title = `${action} ${sectionTitle}`;
      panel.hidden = expanded;
    });
  });
})();
