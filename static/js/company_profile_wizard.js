(function () {
  const wizard = document.getElementById("company-profile-wizard");
  if (!wizard) return;

  const panels = Array.from(wizard.querySelectorAll("[data-step-panel]"));
  const steps = Array.from(wizard.querySelectorAll("[data-step-target]"));
  let activeStep = 0;

  function showStep(index, moveFocus) {
    activeStep = Math.max(0, Math.min(index, panels.length - 1));
    wizard.style.setProperty("--step-progress", `${(activeStep / Math.max(1, panels.length - 1)) * 100}%`);
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
      window.scrollTo({ top: wizard.getBoundingClientRect().top + window.scrollY - 100, behavior: "smooth" });
    }
  }

  wizard.addEventListener("click", (event) => {
    const next = event.target.closest(".prep-next");
    const back = event.target.closest(".prep-back");
    const target = event.target.closest("[data-step-target]");
    if (next) {
      const invalid = panels[activeStep].querySelector(":invalid");
      if (invalid) invalid.reportValidity();
      else showStep(activeStep + 1, true);
    } else if (back) {
      showStep(activeStep - 1, true);
    } else if (target) {
      showStep(Number(target.dataset.stepTarget), true);
    }
  });

  showStep(0, false);
})();
