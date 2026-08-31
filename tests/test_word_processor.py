"""
Unit tests for word_processor module.
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import date

from src.word_processor import WordProcessor, TemplateLookupError


class TestWordProcessor:
    """Tests for WordProcessor class."""

    @pytest.fixture
    def wp(self):
        """Create a WordProcessor instance."""
        # Patch pythoncom and win32com to avoid errors during initialization
        with patch("pythoncom.CoInitialize"), patch(
            "src.word_processor.win32_client.Dispatch"
        ):
            wp = WordProcessor()
            yield wp

    def test_init(self, wp):
        """WordProcessor should initialize with default values."""
        assert wp.word_app is None
        assert wp._initialized is False
        assert wp._template_cache == {}

    def test_find_template_file_exact_match(self, wp, tmp_path):
        """Should find template with exact match."""
        # Create dummy templates
        (tmp_path / "Monday.docx").write_text("dummy")
        (tmp_path / "Tuesday.docx").write_text("dummy")

        result = wp.find_template_file(str(tmp_path), "Monday")
        assert result is not None
        assert result.endswith("Monday.docx")

    def test_find_template_file_cache_usage(self, wp, tmp_path):
        """Should use cache for subsequent lookups."""
        (tmp_path / "Monday.docx").write_text("dummy")

        # First call builds cache
        wp.find_template_file(str(tmp_path), "Monday")
        assert str(tmp_path.resolve()) in wp._template_cache

        # Modify folder (add file) but cache should still be used
        (tmp_path / "Tuesday.docx").write_text("dummy")
        result = wp.find_template_file(str(tmp_path), "Tuesday")
        # Implementation refreshes the folder cache once on a miss.
        assert result is not None
        assert result.endswith("Tuesday.docx")

    def test_robust_template_matching(self, wp, tmp_path):
        """Should match 'Thursday Night' when searching for 'Thursday' if unique."""
        (tmp_path / "Thursday Night.docx").write_text("dummy")
        (tmp_path / "Friday.docx").write_text("dummy")

        result = wp.find_template_file(str(tmp_path), "Thursday")
        assert result is not None
        assert result.endswith("Thursday Night.docx")

    def test_robust_template_matching_boundary(self, wp, tmp_path):
        """Should NOT match 'THIRD Thursday' when searching for 'Thursday'."""
        (tmp_path / "THIRD Thursday.docx").write_text("dummy")

        result = wp.find_template_file(str(tmp_path), "Thursday")
        assert result is None

    def test_ambiguous_template_matching(self, wp, tmp_path):
        """Should handle ambiguous matches gracefully."""
        (tmp_path / "Thursday.docx").write_text("dummy")
        (tmp_path / "Thursday Night.docx").write_text("dummy")

        # "Thursday" matches both. It should prefer the one starting with "Thursday"
        # or the exact match.
        result = wp.find_template_file(str(tmp_path), "Thursday")
        assert result is not None
        assert result.endswith("Thursday.docx")

    def test_permanent_server_error_is_not_retried(self, wp):
        """A permanent COM fault must fail fast instead of burning retries."""
        call = MagicMock(side_effect=Exception("The server threw an exception"))

        with pytest.raises(Exception, match="threw an exception"):
            wp.safe_com_call(call, retries=3, delay=0)

        assert call.call_count == 1

    def test_busy_server_error_is_retried(self, wp):
        """A genuinely transient COM fault must still be retried."""
        call = MagicMock(
            side_effect=[Exception("Server is busy"), Exception("Server is busy"), "ok"]
        )

        assert wp.safe_com_call(call, retries=3, delay=0) == "ok"
        assert call.call_count == 3

    def test_colliding_normalized_names_raise(self, wp, tmp_path):
        """Two files that normalize to the same name must not silently shadow."""
        (tmp_path / "Thursday Night.docx").write_text("dummy")
        (tmp_path / "Thursday  Night.docx").write_text("dummy")

        with pytest.raises(TemplateLookupError) as exc:
            wp.find_template_file(str(tmp_path), "Thursday Night")

        message = str(exc.value)
        assert "Thursday Night.docx" in message
        assert "Thursday  Night.docx" in message

    def test_collision_check_does_not_break_normal_lookup(self, wp, tmp_path):
        """A folder without collisions must resolve exactly as before."""
        (tmp_path / "Monday.docx").write_text("dummy")
        (tmp_path / "Thursday Night.docx").write_text("dummy")
        (tmp_path / "THIRD Thursday.docx").write_text("dummy")

        assert wp.find_template_file(str(tmp_path), "Monday").endswith("Monday.docx")
        assert wp.find_template_file(str(tmp_path), "Thursday").endswith(
            "Thursday Night.docx"
        )
        assert wp.find_template_file(str(tmp_path), "THIRD Thursday").endswith(
            "THIRD Thursday.docx"
        )

    def test_replace_dates_logic(self, wp):
        """Should call find/replace with correct patterns."""
        mock_doc = MagicMock()
        current_date = date(2026, 1, 15)  # Thursday

        with patch.object(wp, "_normalize_spaces_in_doc"), patch.object(
            wp, "_execute_replace", return_value=True
        ) as mock_exec:
            replacements = wp.replace_dates(mock_doc, current_date)

            # Should be called 6 times: 3 ordinal-suffix patterns + 3 plain patterns.
            # All patterns run independently; overlap is prevented by
            # ordering (most-specific first) and tighter wildcard constraints.
            assert mock_exec.call_count == 6

            # Verify the replacement texts include the "with comma" pattern
            # Replacement: "Thursday, January 15, 2026"
            calls = [c[0][2] for c in mock_exec.call_args_list]
            assert "Thursday, January 15, 2026" in calls
            assert replacements == 6

    @patch("src.word_processor.pythoncom.CoInitialize")
    @patch("src.word_processor.win32_client.DispatchEx", create=True)
    def test_initialize_prefers_a_dedicated_word_process(
        self, mock_dispatch_ex, mock_coinit
    ):
        """DispatchEx is the production path: it avoids attaching to the
        operator's own interactive Word session."""
        # initialize() only takes this branch when the callable comes from
        # win32com, which is how it behaves on a real Windows machine.
        mock_dispatch_ex.__module__ = "win32com.client"

        wp = WordProcessor()
        wp.initialize()

        assert wp._initialized is True
        assert wp.word_app is not None
        mock_coinit.assert_called_once()
        mock_dispatch_ex.assert_called_once_with("Word.Application")

    @patch("src.word_processor.pythoncom.CoInitialize")
    @patch("src.word_processor.win32_client.Dispatch")
    @patch("src.word_processor.win32_client.DispatchEx", new=None, create=True)
    def test_initialize_falls_back_to_dispatch(self, mock_dispatch, mock_coinit):
        """Builds without DispatchEx must still start Word."""
        wp = WordProcessor()
        wp.initialize()

        assert wp._initialized is True
        assert wp.word_app is not None
        mock_coinit.assert_called_once()
        mock_dispatch.assert_called_with("Word.Application")

    @patch("src.word_processor.pythoncom.CoInitialize")
    @patch("src.word_processor.pythoncom.CoUninitialize")
    @patch("src.word_processor.win32_client.Dispatch")
    @patch("src.word_processor.win32_client.DispatchEx", new=None, create=True)
    def test_initialize_fails_closed_when_macros_cannot_be_disabled(
        self, mock_dispatch, mock_couninit, mock_coinit
    ):
        """Word automation must not continue when macro hardening fails."""
        app = MagicMock()
        type(app).AutomationSecurity = property(
            fset=MagicMock(side_effect=Exception("policy denied"))
        )
        mock_dispatch.return_value = app

        wp = WordProcessor()

        with pytest.raises(RuntimeError, match="policy denied"):
            wp.initialize()

        app.Quit.assert_called_once()
        mock_coinit.assert_called_once()
        mock_couninit.assert_called_once()
        assert wp.word_app is None
        assert wp._initialized is False

    def test_safe_com_call_retry(self, wp):
        """Safe COM call should retry on genuinely transient COM faults."""
        mock_func = MagicMock()
        # Fail twice with real transient COM messages, then succeed
        mock_func.side_effect = [
            Exception("Call was rejected by callee"),
            Exception("The message filter indicated that the application is busy"),
            "Success",
        ]

        with patch("time.sleep"):  # Don't actually wait
            result = wp.safe_com_call(mock_func, "arg1", retries=3)

        assert result == "Success"
        assert mock_func.call_count == 3

    def test_safe_com_call_fail(self, wp):
        """Safe COM call should eventually fail."""
        mock_func = MagicMock(side_effect=Exception("Permanent Failure"))

        with pytest.raises(Exception, match="Permanent Failure"):
            wp.safe_com_call(mock_func, retries=2)

    def test_clear_template_cache(self, wp, tmp_path):
        """Should clear the template cache."""
        (tmp_path / "Monday.docx").write_text("dummy")
        wp.find_template_file(str(tmp_path), "Monday")
        assert str(tmp_path.resolve()) in wp._template_cache

        wp.clear_template_cache()
        assert wp._template_cache == {}

    def test_find_template_third_thursday_extra_spaces(self, wp, tmp_path):
        """Should find 'THIRD Thursday' even if filename has extra spaces."""
        (tmp_path / "THIRD  Thursday.docx").write_text("dummy")

        result = wp.find_template_file(str(tmp_path), "THIRD Thursday")
        assert result is not None
        assert "Thursday" in result

    def test_third_thursday_integration(self, wp, tmp_path):
        """Integration: scheduler template name should find the right file."""
        from src.scheduler import get_shift_template_name

        (tmp_path / "Thursday.docx").write_text("dummy")
        (tmp_path / "THIRD Thursday.docx").write_text("dummy")

        # January 15, 2026 is the third Thursday
        template_name = get_shift_template_name(date(2026, 1, 15), "day")
        assert template_name == "THIRD Thursday"

        result = wp.find_template_file(str(tmp_path), template_name)
        assert result is not None
        assert "third" in Path(result).name.lower()

    def test_replace_dates_no_match_warning(self, wp):
        """Should log warning when no date patterns match."""
        mock_doc = MagicMock()
        current_date = date(2026, 1, 14)  # Wednesday

        with patch.object(wp, "_normalize_spaces_in_doc"), patch.object(
            wp, "_execute_replace", return_value=False
        ), patch("src.word_processor.logger") as mock_logger:
            replacements = wp.replace_dates(mock_doc, current_date)
            mock_logger.warning.assert_called()
            assert replacements == 0

    def test_normalize_spaces_called_before_patterns(self, wp):
        """Should normalize non-breaking spaces before running date patterns."""
        mock_doc = MagicMock()
        current_date = date(2026, 1, 14)

        call_order = []

        def track_normalize(doc, **kwargs):
            call_order.append("normalize")

        def track_execute(doc, find_text, replace_text, **kwargs):
            call_order.append("execute")
            return False

        with patch.object(
            wp, "_normalize_spaces_in_doc", side_effect=track_normalize
        ), patch.object(wp, "_execute_replace", side_effect=track_execute):
            wp.replace_dates(mock_doc, current_date)

        assert call_order[0] == "normalize"
        assert "execute" in call_order

    def test_run_find_replace_returns_bool(self, wp):
        """_run_find_replace should return True when pattern matches."""
        mock_range = MagicMock()
        mock_range.Find.Execute.return_value = True

        result = wp._run_find_replace(mock_range, "pattern", "replacement")
        assert result is True

    def test_run_find_replace_returns_false_on_no_match(self, wp):
        """_run_find_replace should return False when pattern doesn't match."""
        mock_range = MagicMock()
        mock_range.Find.Execute.return_value = False

        result = wp._run_find_replace(mock_range, "pattern", "replacement")
        assert result is False

    @patch("src.word_processor.pythoncom.CoInitialize")
    @patch("src.word_processor.win32_client.Dispatch")
    @patch("src.word_processor.win32_client.DispatchEx", new=None, create=True)
    def test_context_manager_enter_exit(self, mock_dispatch, mock_coinit):
        """Context manager should initialize on enter and shutdown on exit."""
        wp = WordProcessor()
        assert wp._initialized is False

        with wp:
            assert wp._initialized is True
            assert wp.word_app is not None

        # After exit, word_app should be None (shutdown called)
        assert wp.word_app is None
        assert wp._initialized is False

    def test_print_document_happy_path(self, wp, tmp_path):
        """print_document should open, replace dates, print, and close."""
        wp._initialized = True
        wp.word_app = MagicMock()

        # Create a template file so find_template_file resolves it
        (tmp_path / "Wednesday.docx").write_text("dummy")

        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1  # PROTECTION_NONE
        wp.word_app.Documents.Open.return_value = mock_doc

        with patch.object(wp, "safe_com_call", side_effect=lambda f, *a, **kw: f(*a)):
            with patch.object(wp, "replace_dates"):
                success, error = wp.print_document(
                    str(tmp_path),
                    "Wednesday",
                    date(2026, 1, 14),
                    "Test Printer",
                )

        assert success is True
        assert error is None
        # Verify document was opened, printed, and closed
        wp.word_app.Documents.Open.assert_called_once()
        mock_doc.PrintOut.assert_called_once_with(False)
        mock_doc.Close.assert_called()

    def test_print_document_not_initialized(self, wp):
        """print_document should fail if Word is not initialized."""
        wp._initialized = False
        wp.word_app = None
        success, error = wp.print_document("/tmp", "Test", date(2026, 1, 14), "Printer")
        assert success is False
        assert "not initialized" in error.lower()

    def test_safe_com_call_rejects_zero_retries(self, wp):
        """safe_com_call should raise ValueError for retries < 1."""
        with pytest.raises(ValueError, match="retries must be >= 1"):
            wp.safe_com_call(lambda: None, retries=0)

    def test_build_template_cache_filters_lock_files(self, wp, tmp_path):
        """_build_template_cache should skip ~$ lock files and hidden files."""
        (tmp_path / "Monday.docx").write_text("dummy")
        (tmp_path / "~$Monday.docx").write_text("lock")
        (tmp_path / ".hidden.docx").write_text("hidden")

        cache = wp._build_template_cache(str(tmp_path))
        assert "monday" in cache
        assert "~$monday" not in cache
        assert ".hidden" not in cache
        assert len(cache) == 1

    def test_print_document_rejects_path_traversal(self, wp, tmp_path):
        """print_document should reject templates outside the folder."""
        wp._initialized = True
        wp.word_app = MagicMock()

        # Manually place a malicious path in the cache
        folder_path = str(tmp_path.resolve())
        wp._template_cache[folder_path] = {"thursday": ["/etc/passwd"]}

        success, error = wp.print_document(
            str(tmp_path), "Thursday", date(2026, 1, 15), "Printer"
        )
        assert success is False
        assert "outside" in error.lower()

    def test_shutdown_quit_raises(self, wp):
        """shutdown should handle Quit() raising an exception gracefully."""
        wp._initialized = True
        wp._com_initialized = True
        mock_app = MagicMock()
        mock_app.Quit.side_effect = Exception("COM server crashed")
        wp.word_app = mock_app

        # Should not raise
        wp.shutdown()

        # word_app should be cleared even when Quit fails
        assert wp.word_app is None
        assert wp._initialized is False
        assert wp._com_initialized is False

    def test_shutdown_couninitialize_raises(self, wp):
        """shutdown should handle CoUninitialize() raising an exception."""
        wp._initialized = True
        wp._com_initialized = True
        wp.word_app = MagicMock()

        with patch("src.word_processor.pythoncom.CoUninitialize") as mock_uninit:
            mock_uninit.side_effect = Exception("Thread mismatch")
            wp.shutdown()

        assert wp.word_app is None
        assert wp._initialized is False
        # _com_initialized should still be reset in the finally block
        assert wp._com_initialized is False

    def test_print_document_protected_document(self, wp, tmp_path):
        """print_document should unprotect a protected document before printing."""
        wp._initialized = True
        wp.word_app = MagicMock()

        (tmp_path / "Wednesday.docx").write_text("dummy")

        mock_doc = MagicMock()
        mock_doc.ProtectionType = 3  # PROTECTION_READ_ONLY
        wp.word_app.Documents.Open.return_value = mock_doc

        with patch.object(wp, "safe_com_call", side_effect=lambda f, *a, **kw: f(*a)):
            with patch.object(wp, "replace_dates"):
                success, error = wp.print_document(
                    str(tmp_path), "Wednesday", date(2026, 1, 14), "Printer"
                )

        assert success is True
        mock_doc.Unprotect.assert_called_once()

    def test_print_document_active_printer_failure(self, wp, tmp_path):
        """print_document must not fall back to an unintended printer."""
        wp._initialized = True
        wp.word_app = MagicMock()

        (tmp_path / "Wednesday.docx").write_text("dummy")

        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1  # PROTECTION_NONE
        wp.word_app.Documents.Open.return_value = mock_doc

        # Make ActivePrinter assignment raise
        type(wp.word_app).ActivePrinter = property(
            fget=lambda s: "default",
            fset=MagicMock(side_effect=Exception("Printer not found")),
        )

        with patch.object(wp, "safe_com_call", side_effect=lambda f, *a, **kw: f(*a)):
            with patch.object(wp, "replace_dates"):
                success, error = wp.print_document(
                    str(tmp_path), "Wednesday", date(2026, 1, 14), "Bad Printer"
                )

        assert success is False
        assert "Printer not found" in (error or "")
        mock_doc.PrintOut.assert_not_called()

    def test_print_document_no_date_replacement_blocks_print(self, wp, tmp_path):
        """A template with no supported date must not be printed unchanged."""
        wp._initialized = True
        wp.word_app = MagicMock()
        (tmp_path / "Wednesday.docx").write_text("dummy")

        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1  # PROTECTION_NONE
        wp.word_app.Documents.Open.return_value = mock_doc

        with patch.object(wp, "safe_com_call", side_effect=lambda f, *a, **kw: f(*a)):
            with patch.object(wp, "replace_dates", return_value=0):
                success, error = wp.print_document(
                    str(tmp_path), "Wednesday", date(2026, 1, 14), "Printer"
                )

        assert success is False
        assert "date" in (error or "").lower()
        mock_doc.PrintOut.assert_not_called()

    def test_print_document_closes_on_printout_error(self, wp, tmp_path):
        """print_document finally block should close doc if PrintOut raises."""
        wp._initialized = True
        wp.word_app = MagicMock()

        (tmp_path / "Wednesday.docx").write_text("dummy")

        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1  # PROTECTION_NONE
        mock_doc.PrintOut.side_effect = Exception("Printer offline")
        wp.word_app.Documents.Open.return_value = mock_doc

        with patch.object(wp, "safe_com_call", side_effect=lambda f, *a, **kw: f(*a)):
            with patch.object(wp, "replace_dates"):
                success, error = wp.print_document(
                    str(tmp_path), "Wednesday", date(2026, 1, 14), "Printer"
                )

        assert success is False
        assert "Printer offline" in error
        # The finally block should attempt to close the document
        # doc.Close is called in the finally via safe_com_call
        close_calls = [c for c in mock_doc.Close.call_args_list]
        assert len(close_calls) >= 1

    def test_print_document_unprotect_fails_and_stays_protected(self, wp, tmp_path):
        """print_document should return failure when Unprotect fails and doc remains protected."""
        wp._initialized = True
        wp.word_app = MagicMock()

        (tmp_path / "Wednesday.docx").write_text("dummy")

        mock_doc = MagicMock()
        # Document is protected and stays protected after Unprotect fails
        mock_doc.ProtectionType = 3  # PROTECTION_READ_ONLY

        def unprotect_fails():
            raise Exception("Password required")

        mock_doc.Unprotect = unprotect_fails
        wp.word_app.Documents.Open.return_value = mock_doc

        with patch.object(wp, "safe_com_call", side_effect=lambda f, *a, **kw: f(*a)):
            success, error = wp.print_document(
                str(tmp_path), "Wednesday", date(2026, 1, 14), "Printer"
            )

        assert success is False
        assert "protected" in error.lower()
        # PrintOut should NOT have been called (doc was not printable)
        mock_doc.PrintOut.assert_not_called()
        # Document should still be closed
        mock_doc.Close.assert_called()

    def test_print_document_opens_readonly(self, wp, tmp_path):
        """print_document should open documents with ReadOnly=True (third positional arg)."""
        wp._initialized = True
        wp.word_app = MagicMock()

        (tmp_path / "Wednesday.docx").write_text("dummy")

        mock_doc = MagicMock()
        mock_doc.ProtectionType = -1  # PROTECTION_NONE
        wp.word_app.Documents.Open.return_value = mock_doc

        call_log = []

        def tracking_safe_com_call(f, *a, **kw):
            call_log.append((f, a, kw))
            return f(*a)

        with patch.object(wp, "safe_com_call", side_effect=tracking_safe_com_call):
            with patch.object(wp, "replace_dates"):
                success, error = wp.print_document(
                    str(tmp_path), "Wednesday", date(2026, 1, 14), "Printer"
                )

        assert success is True
        # The first safe_com_call should be Documents.Open with ReadOnly=True
        # Documents.Open(filename, False, True) — third arg (True) is ReadOnly
        open_call = call_log[0]
        open_args = open_call[1]  # positional args after the function
        # open_args should be (target_file, False, True)
        assert len(open_args) >= 3
        assert open_args[2] is True  # ReadOnly=True
