from legal_bot.utils import check_file_type, format_answer, get_file_size_mb


class TestCheckFileType:
    def test_accepts_pdf(self):
        assert check_file_type("document.pdf") is True

    def test_accepts_docx_case_insensitive(self):
        assert check_file_type("Report.DOCX") is True

    def test_accepts_txt(self):
        assert check_file_type("notes.txt") is True

    def test_rejects_jpg(self):
        assert check_file_type("image.jpg") is False

    def test_rejects_empty(self):
        assert check_file_type("") is False

    def test_rejects_none(self):
        assert check_file_type(None) is False


class TestFormatAnswer:
    def test_short_answer_returns_single_part(self):
        assert format_answer("hello", max_length=4096) == ["hello"]

    def test_long_answer_is_split_into_multiple_parts(self):
        text = "abc\n\n" * 2000
        parts = format_answer(text, max_length=100)
        assert len(parts) > 1
        assert "".join(parts) == text

    def test_split_prefers_double_newline_boundary(self):
        first_block = "x" * 50
        second_block = "y" * 50
        text = f"{first_block}\n\n{second_block}"
        parts = format_answer(text, max_length=80)
        assert parts[0].endswith("\n\n") or parts[0].endswith("\n")


class TestGetFileSizeMb:
    def test_missing_file_returns_zero(self):
        assert get_file_size_mb("/nonexistent/path/to/file.bin") == 0

    def test_existing_file(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"x" * (1024 * 1024))
        assert abs(get_file_size_mb(str(f)) - 1.0) < 0.01
