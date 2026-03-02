from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from bot import (
    COOLDOWN,
    MODELS,
    StockMonitor,
    _build_request,
    _decode_varint,
    _encode_varint,
    _parse_response,
    check_stock,
    send_telegram,
)


# --- protobuf helpers ---


class TestEncodeVarint:
    def test_single_byte(self):
        assert _encode_varint(0) == b"\x00"
        assert _encode_varint(1) == b"\x01"
        assert _encode_varint(127) == b"\x7f"

    def test_two_bytes(self):
        assert _encode_varint(128) == b"\x80\x01"
        assert _encode_varint(300) == b"\xac\x02"

    def test_large_value(self):
        # 903905 = package id for 64 GB LCD
        encoded = _encode_varint(903905)
        decoded, _ = _decode_varint(encoded)
        assert decoded == 903905


class TestDecodeVarint:
    def test_single_byte(self):
        val, off = _decode_varint(b"\x05", 0)
        assert val == 5
        assert off == 1

    def test_multi_byte(self):
        val, off = _decode_varint(b"\xac\x02", 0)
        assert val == 300
        assert off == 2

    def test_with_offset(self):
        data = b"\xff\x08\xac\x02"
        val, off = _decode_varint(data, 2)
        assert val == 300

    def test_roundtrip_all_package_ids(self):
        for pkg_id in MODELS:
            encoded = _encode_varint(pkg_id)
            decoded, _ = _decode_varint(encoded)
            assert decoded == pkg_id


class TestBuildRequest:
    def test_known_encoding(self):
        """Verify our encoder matches what Chrome captured for package 903905 + NL."""
        import base64

        result = _build_request(903905, "NL")
        raw = base64.b64decode(result)
        # field 1 tag (0x08) + varint(903905) + field 2 tag (0x12) + len(2) + "NL"
        assert raw[-2:] == b"NL"
        assert raw[0] == 0x08
        # Decode field 1
        val, off = _decode_varint(raw, 1)
        assert val == 903905
        assert raw[off] == 0x12  # field 2 tag

    def test_all_models_produce_valid_protobuf(self):
        import base64

        for pkg_id in MODELS:
            encoded = _build_request(pkg_id, "NL")
            raw = base64.b64decode(encoded)
            assert raw[0] == 0x08
            val, off = _decode_varint(raw, 1)
            assert val == pkg_id
            assert raw[-2:] == b"NL"


class TestParseResponse:
    def test_not_available(self):
        # field1=0, field2=0 → out of stock (captured from live API)
        data = bytes([0x08, 0x00, 0x10, 0x00])
        assert _parse_response(data) is False

    def test_available(self):
        # field1=1 → in stock
        data = bytes([0x08, 0x01, 0x10, 0x00])
        assert _parse_response(data) is True

    def test_empty(self):
        assert _parse_response(b"") is False

    def test_only_field1_true(self):
        data = bytes([0x08, 0x01])
        assert _parse_response(data) is True


# --- check_stock ---


class TestCheckStock:
    def test_all_out_of_stock(self):
        mock_resp = MagicMock()
        mock_resp.content = bytes([0x08, 0x00, 0x10, 0x00])
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        results = check_stock(session=mock_session)
        assert len(results) == len(MODELS)
        assert all(v is False for v in results.values())
        assert mock_session.get.call_count == len(MODELS)

    def test_one_in_stock(self):
        def side_effect(*args, **kwargs):
            encoded_param = kwargs.get("params", {}).get("input_protobuf_encoded", "")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            # Make the first call return "in stock"
            if side_effect.call_count == 0:
                resp.content = bytes([0x08, 0x01, 0x10, 0x00])
            else:
                resp.content = bytes([0x08, 0x00, 0x10, 0x00])
            side_effect.call_count += 1
            return resp

        side_effect.call_count = 0

        mock_session = MagicMock()
        mock_session.get.side_effect = side_effect

        results = check_stock(session=mock_session)
        assert sum(v is True for v in results.values()) == 1

    def test_network_error_returns_false(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("Connection timeout")

        results = check_stock(session=mock_session)
        assert all(v is False for v in results.values())


# --- send_telegram ---


class TestSendTelegram:
    @patch("bot.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        assert send_telegram("test") is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "chat_id" in call_kwargs.kwargs["json"]

    @patch("bot.requests.post")
    def test_failure(self, mock_post):
        mock_post.side_effect = Exception("Network error")
        assert send_telegram("test") is False


# --- StockMonitor ---


class TestStockMonitor:
    @patch("bot.send_telegram")
    @patch("bot.check_stock")
    def test_sends_alert_on_stock(self, mock_check, mock_tg):
        mock_check.return_value = {pkg: False for pkg in MODELS}
        first_pkg = list(MODELS.keys())[0]
        mock_check.return_value[first_pkg] = True
        mock_tg.return_value = True

        monitor = StockMonitor()
        monitor.run_check()

        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        assert MODELS[first_pkg] in msg

    @patch("bot.send_telegram")
    @patch("bot.check_stock")
    def test_no_alert_when_all_out_of_stock(self, mock_check, mock_tg):
        mock_check.return_value = {pkg: False for pkg in MODELS}

        monitor = StockMonitor()
        monitor.run_check()

        mock_tg.assert_not_called()

    @patch("bot.send_telegram")
    @patch("bot.check_stock")
    def test_cooldown_suppresses_repeat_alert(self, mock_check, mock_tg):
        first_pkg = list(MODELS.keys())[0]
        mock_check.return_value = {pkg: False for pkg in MODELS}
        mock_check.return_value[first_pkg] = True
        mock_tg.return_value = True

        monitor = StockMonitor()

        # First check → should alert
        monitor.run_check()
        assert mock_tg.call_count == 1

        # Second check → should be suppressed (within 1 hour)
        monitor.run_check()
        assert mock_tg.call_count == 1  # still 1, no new call

    @patch("bot.send_telegram")
    @patch("bot.check_stock")
    def test_alert_resumes_after_cooldown(self, mock_check, mock_tg):
        first_pkg = list(MODELS.keys())[0]
        mock_check.return_value = {pkg: False for pkg in MODELS}
        mock_check.return_value[first_pkg] = True
        mock_tg.return_value = True

        monitor = StockMonitor()

        # First check → alert
        monitor.run_check()
        assert mock_tg.call_count == 1

        # Expire the cooldown
        monitor.cooldowns[first_pkg] = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Third check → should alert again
        monitor.run_check()
        assert mock_tg.call_count == 2

    @patch("bot.send_telegram")
    @patch("bot.check_stock")
    def test_multiple_models_in_stock(self, mock_check, mock_tg):
        mock_check.return_value = {pkg: True for pkg in MODELS}
        mock_tg.return_value = True

        monitor = StockMonitor()
        monitor.run_check()

        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        for name in MODELS.values():
            assert name in msg

    @patch("bot.send_telegram")
    @patch("bot.check_stock")
    def test_cooldown_is_per_model(self, mock_check, mock_tg):
        pkgs = list(MODELS.keys())
        mock_tg.return_value = True

        monitor = StockMonitor()

        # Check 1: only first model in stock
        mock_check.return_value = {pkg: False for pkg in MODELS}
        mock_check.return_value[pkgs[0]] = True
        monitor.run_check()
        assert mock_tg.call_count == 1

        # Check 2: first model still in stock (suppressed), second model now in stock
        mock_check.return_value[pkgs[1]] = True
        monitor.run_check()
        assert mock_tg.call_count == 2
        msg = mock_tg.call_args[0][0]
        # Should only mention the second model (first is suppressed)
        assert MODELS[pkgs[1]] in msg
        assert MODELS[pkgs[0]] not in msg
