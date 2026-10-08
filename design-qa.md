# Design QA — Planning guided flow

## Source and implementation

- Source reference: `/Users/rromanit/.codex/generated_images/01a11753-f364-7b63-bd15-21c68469386a/exec-9ff11ea6-5ccb-4797-a51a-1b106c76a7ca.png`
- Source size: 1487 × 1058 px.
- Implementation state: `/planificacion`, step 2 “Comprobar”, completed invalid preview with four heaters excluded by missing telemetry.
- Implementation capture: `.artifacts/design-qa/planning-check-1440.png`, 1440 × 1024 px.
- Combined comparison: `.artifacts/design-qa/reference-vs-implementation.png`.
- Responsive captures: `.artifacts/design-qa/planning-tablet.png` at 1024 × 768 and `.artifacts/design-qa/planning-mobile.png` at 390 × 844.

## Comparison result

The implementation preserves the selected direction's defining hierarchy: existing application shell, compact three-step workflow, a single dominant result banner, checked consignments and affected heaters in two focused panels, and explicit bottom actions. The implementation intentionally retains the product's real typography, navigation, controls, and backend-derived wording rather than reproducing text invented by the visual reference.

The primary flow starts at “Consignas”. “Comprobar” presents the actionable result before the technical calculation checks. “Activar” remains disabled when the preview is invalid or stale. Plan history, active-plan charts, forecast data, and all graph detail actions are contained under the separate “Análisis y datos” view.

No focus-region-only comparison was needed: both the complete selected reference and the complete implementation state fit in the combined comparison and were inspected together.

## Fidelity surfaces

- Layout and hierarchy: passed. The primary task is separated from read-only analysis and uses the same left-shell/content relationship as the reference.
- Typography and density: passed. Headings, labels, helper copy, and compact rows follow the existing application system and preserve readable contrast.
- Color and surfaces: passed. Neutral canvas, white cards, blue progress/action color, green valid state, and red blocking state align with the reference.
- Spacing and alignment: passed after separating the section lead from its heading and moving the result above calculation checks.
- Content fidelity: passed. Real heater names, schedules, preview status, and telemetry causes are rendered from application data.
- Empty states: passed. An invalid preview with no intervals shows an explanatory empty state instead of an empty chart.
- Responsive behavior: passed. `scrollWidth === clientWidth` at 1440, 1024, and 390 px. The master-detail editor becomes one column at tablet width and the workflow becomes stacked on mobile.
- Accessibility: passed. Step navigation exposes current/disabled state, headings label sections, status/error messages use live semantics, and controls keep explicit accessible names.

## Interaction checks

- Opened “Análisis y datos” and returned to the guided flow.
- Started a real preview calculation and observed queued, completed, and invalid states.
- Confirmed four excluded heaters are grouped under one telemetry cause.
- Confirmed “Continuar a activar” remains disabled for the invalid preview.
- Opened and closed the detailed problem dialog.
- Confirmed the preview empty state is visible when there are no intervals.
- Browser console contains no application errors. One unrelated password-manager extension error was observed and excluded.

## Iterations

1. Split planning into “Consignas”, “Comprobar”, and “Activar”; moved charts/history/forecast into “Análisis y datos”.
2. Fixed a section-header flex rule that placed lead copy beside the heading.
3. Increased the master-detail collapse breakpoint for the application's persistent sidebar.
4. Grouped problems by root cause and exposed the cause description with each affected heater.
5. Reordered the completed-preview view so the actionable result precedes technical checks.

final result: passed
