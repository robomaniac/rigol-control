"""Offline document rendering. This package never imports instrument code."""

from .renderer import ReportRenderError, render_report, validate_report_model

__all__ = ["ReportRenderError", "render_report", "validate_report_model"]
