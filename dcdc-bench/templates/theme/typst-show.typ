// Quarto template partial (`template-partials` in characterization.qmd). It
// replaces Quarto's default typst-show.typ, whose `#show: doc => article(...)`
// would print a centred title block and its own page and paragraph settings.
// `dcdc-report` comes from templates/theme/print-theme.typ, inserted by the
// renderer through the header include (print-header.typ) together with the
// `dcdc-id` identity dictionary it reads.
#show: doc => dcdc-report(doc)
