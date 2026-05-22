from telegram import InlineKeyboardMarkup

from legal_bot.keyboards import (
    get_main_menu,
    get_ask_question_menu,
    get_admin_menu,
    get_free_questions_menu,
    get_paid_questions_menu,
    get_subscription_menu,
    get_cancel_button,
    get_pending_receipt_control,
    get_issued_receipt_control,
)


def _all_callbacks(markup):
    return [btn.callback_data for row in markup.inline_keyboard for btn in row]


class TestMainMenu:
    def test_anonymous_user_sees_free_and_paid(self):
        kb = get_main_menu(is_admin=False, has_subscription=False)
        assert isinstance(kb, InlineKeyboardMarkup)
        callbacks = _all_callbacks(kb)
        assert "menu_free" in callbacks
        assert "menu_paid" in callbacks
        assert "ask_question" not in callbacks
        assert "admin_panel" not in callbacks

    def test_subscriber_sees_ask_question_button(self):
        kb = get_main_menu(is_admin=False, has_subscription=True)
        callbacks = _all_callbacks(kb)
        assert "ask_question" in callbacks
        assert "menu_free" not in callbacks
        assert "menu_paid" not in callbacks

    def test_admin_sees_admin_panel(self):
        kb = get_main_menu(is_admin=True, has_subscription=False)
        callbacks = _all_callbacks(kb)
        assert "admin_panel" in callbacks


class TestSubmenus:
    def test_ask_question_menu_has_text_and_file_options(self):
        callbacks = _all_callbacks(get_ask_question_menu())
        assert "sub_text" in callbacks
        assert "sub_file" in callbacks

    def test_free_questions_menu(self):
        callbacks = _all_callbacks(get_free_questions_menu())
        assert "free_text" in callbacks
        assert "free_file" in callbacks

    def test_paid_questions_menu(self):
        callbacks = _all_callbacks(get_paid_questions_menu())
        assert "paid_text" in callbacks
        assert "paid_file" in callbacks

    def test_subscription_menu_has_three_durations(self):
        callbacks = _all_callbacks(get_subscription_menu())
        assert "sub_2weeks" in callbacks
        assert "sub_1month" in callbacks
        assert "sub_3months" in callbacks

    def test_admin_menu_pending_count_in_label(self):
        kb = get_admin_menu(pending_count=7)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("7" in label for label in labels)

    def test_cancel_button_returns_to_main_menu(self):
        callbacks = _all_callbacks(get_cancel_button())
        assert callbacks == ["main_menu"]


class TestReceiptControls:
    def test_pending_navigation_when_both_directions_available(self):
        kb = get_pending_receipt_control(paid_request_id=42, has_next=True, has_prev=True)
        callbacks = _all_callbacks(kb)
        assert "admin_mark_issued_42" in callbacks
        assert "admin_prev_pending" in callbacks
        assert "admin_next_pending" in callbacks

    def test_issued_navigation_hides_unavailable_buttons(self):
        kb = get_issued_receipt_control(has_next=False, has_prev=False)
        callbacks = _all_callbacks(kb)
        assert "admin_prev_issued" not in callbacks
        assert "admin_next_issued" not in callbacks
        assert "admin_panel" in callbacks
