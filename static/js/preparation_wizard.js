(function () {
  const form = document.getElementById("bid-preparation-form");
  if (!form) return;

  const panels = Array.from(form.querySelectorAll("[data-step-panel]"));
  const steps = Array.from(form.querySelectorAll("[data-step-target]"));
  let activeStep = 0;
  form.noValidate = true;

  function showStep(index, moveFocus) {
    activeStep = Math.max(0, Math.min(index, panels.length - 1));
    form.style.setProperty("--step-progress", `${(activeStep / Math.max(1, panels.length - 1)) * 100}%`);
    panels.forEach((panel, panelIndex) => {
      panel.hidden = panelIndex !== activeStep;
      panel.setAttribute("aria-hidden", panelIndex === activeStep ? "false" : "true");
    });
    steps.forEach((step, stepIndex) => {
      step.classList.toggle("is-active", stepIndex === activeStep);
      step.classList.toggle("is-complete", stepIndex < activeStep);
      if (stepIndex === activeStep) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    });
    if (moveFocus) {
      const heading = panels[activeStep].querySelector("h2");
      if (heading) {
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
      }
      window.scrollTo({ top: form.getBoundingClientRect().top + window.scrollY - 100, behavior: "smooth" });
    }
  }

  form.addEventListener("click", (event) => {
    const next = event.target.closest(".prep-next");
    const back = event.target.closest(".prep-back");
    const target = event.target.closest("[data-step-target]");
    if (next) {
      const invalid = panels[activeStep].querySelector(":invalid");
      if (invalid) invalid.reportValidity();
      else showStep(activeStep + 1, true);
    }
    else if (back) showStep(activeStep - 1, true);
    else if (target) showStep(Number(target.dataset.stepTarget), true);
  });

  form.addEventListener("submit", (event) => {
    if (event.submitter?.dataset.skipWizardValidation === "true") return;
    for (let index = 0; index < panels.length; index += 1) {
      const invalid = panels[index].querySelector(":invalid");
      if (!invalid) continue;
      event.preventDefault();
      showStep(index, true);
      window.setTimeout(() => invalid.reportValidity(), 0);
      return;
    }
  });

  const requestedStep = new URLSearchParams(window.location.search).get("step");
  showStep(requestedStep === "boq" ? 1 : 0, false);
})();
