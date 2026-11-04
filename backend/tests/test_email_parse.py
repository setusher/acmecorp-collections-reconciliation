from app.services.collections.email_parse import auth_failed, detect_automated, parse_email, strip_quoted
from tests.helpers import make_email


def test_parse_basic_and_normalises_sender():
    raw = make_email("Arjun Nair <Arjun.Nair@Kestrel.TEST>", "Re: [AcmeCorp] Payment reminder", "Hello",
                     in_reply_to="<abc@acme>")
    m = parse_email(raw)
    assert m.from_addr == "arjun.nair@kestrel.test" and m.from_name == "Arjun Nair"
    assert m.in_reply_to == "<abc@acme>" and m.references == ["<abc@acme>"]
    assert m.message_id.startswith("<") and m.body_text.strip() == "Hello"


def test_html_only_email_rendered_as_text():
    raw = make_email("a@b.test", "hi", "<p>Hello <b>there</b><script>alert(1)</script></p>", html=True)
    m = parse_email(raw)
    assert "Hello there" in m.body_text and "script" not in m.body_text and "<" not in m.body_text


def test_strip_quoted_and_signature():
    text = ("Is this the only amount pending?\nThanks\n-- \nArjun\n\nOn Tue, 4 Nov 2026 at 10:00, Acme <a@b> wrote:\n"
            "> Dear Arjun\n> INV-1004 ...")
    assert strip_quoted(text) == "Is this the only amount pending?\nThanks"
    text2 = "Paid yesterday.\n\n-----Original Message-----\nFrom: Acme\nSubject: reminder"
    assert strip_quoted(text2) == "Paid yesterday."


def test_detect_out_of_office_and_bounce():
    ooo = parse_email(make_email("x@c.test", "Automatic reply: Payment reminder", "I am away",
                                 headers={"Auto-Submitted": "auto-replied"}))
    assert detect_automated(ooo) == "auto_reply"
    ooo2 = parse_email(make_email("x@c.test", "Out of Office", "away"))
    assert detect_automated(ooo2) == "auto_reply"
    bounce = parse_email(make_email("MAILER-DAEMON@mail.test", "Delivery Status Notification (Failure)", "failed"))
    assert detect_automated(bounce) == "bounce"
    normal = parse_email(make_email("x@c.test", "Re: reminder", "What do I owe?"))
    assert detect_automated(normal) is None


def test_auth_failure_detected():
    m = parse_email(make_email("x@c.test", "hi", "x",
                               headers={"Authentication-Results": "mx.google.com; spf=fail smtp.mailfrom=c.test"}))
    assert auth_failed(m)
