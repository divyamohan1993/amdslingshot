"""
JalNetra -- Async Multi-Channel Alert Dispatcher

Routes water-quality and system alerts through appropriate channels
based on severity:

  INFO       -> Dashboard only
  WARNING    -> SMS + Dashboard
  CRITICAL   -> SMS + WhatsApp + Dashboard
  EMERGENCY  -> SMS + WhatsApp + Voice Call + Dashboard

Features:
  - SMS delivery via MSG91 API (async httpx)
  - WhatsApp delivery via WhatsApp Business API (async)
  - Voice calls via Bhashini TTS + Twilio (async)
  - Alert templates in 10+ Indian languages
  - Deduplication: same alert suppressed within 1-hour window
  - Rate limiting: max 10 alerts per subscriber per day
  - Acknowledgment tracking with escalation on timeout
  - Full async with retry and timeout on all external calls
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Any

import httpx

logger = logging.getLogger("jalnetra.alert_dispatcher")


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

class AlertSeverity(IntEnum):
    INFO = 1
    WARNING = 2
    CRITICAL = 3
    EMERGENCY = 4


# ---------------------------------------------------------------------------
# Alert templates -- multilingual
# ---------------------------------------------------------------------------

ALERT_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "water_quality": (
            "JalNetra Alert [{severity}]: Water quality issue at Node {node_id}. "
            "{parameter} = {value} {unit} (limit: {limit}). "
            "Action: {action}"
        ),
        "battery_low": (
            "JalNetra: Sensor node {node_id} battery low ({battery}%). "
            "Schedule maintenance."
        ),
        "node_offline": (
            "JalNetra: Sensor node {node_id} has been offline for {minutes} minutes. "
            "Check LoRa connectivity."
        ),
        "depletion_warning": (
            "JalNetra: Groundwater at Node {node_id} predicted to deplete to "
            "critical level in {days} days. Current level: {level} cm."
        ),
    },
    "hi": {
        "water_quality": (
            "जलनेत्र चेतावनी [{severity}]: नोड {node_id} पर जल गुणवत्ता समस्या। "
            "{parameter} = {value} {unit} (सीमा: {limit})। "
            "कार्रवाई: {action}"
        ),
        "battery_low": (
            "जलनेत्र: सेंसर नोड {node_id} की बैटरी कम ({battery}%)। "
            "रखरखाव की योजना बनाएं।"
        ),
        "node_offline": (
            "जलनेत्र: सेंसर नोड {node_id} पिछले {minutes} मिनट से ऑफ़लाइन है। "
            "LoRa कनेक्टिविटी की जांच करें।"
        ),
        "depletion_warning": (
            "जलनेत्र: नोड {node_id} पर भूजल {days} दिनों में गंभीर स्तर पर "
            "पहुंचने का अनुमान। वर्तमान स्तर: {level} सेमी।"
        ),
    },
    "ta": {
        "water_quality": (
            "ஜல்நேத்ரா எச்சரிக்கை [{severity}]: நோட் {node_id} இல் நீர் தர சிக்கல். "
            "{parameter} = {value} {unit} (வரம்பு: {limit}). "
            "நடவடிக்கை: {action}"
        ),
        "battery_low": (
            "ஜல்நேத்ரா: சென்சார் நோட் {node_id} பேட்டரி குறைவு ({battery}%). "
            "பராமரிப்பை திட்டமிடுங்கள்."
        ),
        "node_offline": (
            "ஜல்நேத்ரா: சென்சார் நோட் {node_id} கடந்த {minutes} நிமிடங்களாக "
            "ஆஃப்லைனில் உள்ளது."
        ),
        "depletion_warning": (
            "ஜல்நேத்ரா: நோட் {node_id} இல் நிலத்தடி நீர் {days} நாட்களில் "
            "ஆபத்தான நிலையை எட்டும் என கணிக்கப்படுகிறது."
        ),
    },
    "te": {
        "water_quality": (
            "జల్‌నేత్ర హెచ్చరిక [{severity}]: నోడ్ {node_id} వద్ద నీటి నాణ్యత సమస్య. "
            "{parameter} = {value} {unit} (పరిమితి: {limit}). "
            "చర్య: {action}"
        ),
        "battery_low": (
            "జల్‌నేత్ర: సెన్సార్ నోడ్ {node_id} బ్యాటరీ తక్కువ ({battery}%). "
            "నిర్వహణ షెడ్యూల్ చేయండి."
        ),
        "node_offline": (
            "జల్‌నేత్ర: సెన్సార్ నోడ్ {node_id} గత {minutes} నిమిషాలుగా ఆఫ్‌లైన్."
        ),
        "depletion_warning": (
            "జల్‌నేత్ర: నోడ్ {node_id} వద్ద భూగర్భ జలాలు {days} రోజుల్లో "
            "క్లిష్ట స్థాయికి చేరుకుంటాయని అంచనా."
        ),
    },
    "kn": {
        "water_quality": (
            "ಜಲನೇತ್ರ ಎಚ್ಚರಿಕೆ [{severity}]: ನೋಡ್ {node_id} ನಲ್ಲಿ ನೀರಿನ ಗುಣಮಟ್ಟ ಸಮಸ್ಯೆ. "
            "{parameter} = {value} {unit} (ಮಿತಿ: {limit}). "
            "ಕ್ರಮ: {action}"
        ),
        "battery_low": (
            "ಜಲನೇತ್ರ: ಸೆನ್ಸರ್ ನೋಡ್ {node_id} ಬ್ಯಾಟರಿ ಕಡಿಮೆ ({battery}%). "
            "ನಿರ್ವಹಣೆ ಯೋಜಿಸಿ."
        ),
        "node_offline": (
            "ಜಲನೇತ್ರ: ಸೆನ್ಸರ್ ನೋಡ್ {node_id} ಕಳೆದ {minutes} ನಿಮಿಷಗಳಿಂದ ಆಫ್‌ಲೈನ್."
        ),
        "depletion_warning": (
            "ಜಲನೇತ್ರ: ನೋಡ್ {node_id} ನಲ್ಲಿ ಅಂತರ್ಜಲ {days} ದಿನಗಳಲ್ಲಿ "
            "ಗಂಭೀರ ಮಟ್ಟಕ್ಕೆ ಇಳಿಯುವ ಮುನ್ಸೂಚನೆ."
        ),
    },
    "ml": {
        "water_quality": (
            "ജല്‍നേത്ര മുന്നറിയിപ്പ് [{severity}]: നോഡ് {node_id} ല്‍ ജലഗുണനിലവാര പ്രശ്നം. "
            "{parameter} = {value} {unit} (പരിധി: {limit}). "
            "നടപടി: {action}"
        ),
        "battery_low": (
            "ജല്‍നേത്ര: സെന്‍സര്‍ നോഡ് {node_id} ബാറ്ററി കുറവ് ({battery}%). "
            "മെയിന്റനന്‍സ് ഷെഡ്യൂള്‍ ചെയ്യുക."
        ),
        "node_offline": (
            "ജല്‍നേത്ര: സെന്‍സര്‍ നോഡ് {node_id} കഴിഞ്ഞ {minutes} മിനിറ്റുകളായി ഓഫ്‌ലൈന്‍."
        ),
        "depletion_warning": (
            "ജല്‍നേത്ര: നോഡ് {node_id} ലെ ഭൂഗര്‍ഭജലം {days} ദിവസങ്ങള്‍ക്കുള്ളില്‍ "
            "ഗുരുതര നിലയിലേക്ക് താഴുമെന്ന് കണക്കാക്കുന്നു."
        ),
    },
    "bn": {
        "water_quality": (
            "জলনেত্র সতর্কতা [{severity}]: নোড {node_id}-এ জলের গুণমান সমস্যা। "
            "{parameter} = {value} {unit} (সীমা: {limit})। "
            "পদক্ষেপ: {action}"
        ),
        "battery_low": (
            "জলনেত্র: সেন্সর নোড {node_id}-এর ব্যাটারি কম ({battery}%)। "
            "রক্ষণাবেক্ষণের পরিকল্পনা করুন।"
        ),
        "node_offline": (
            "জলনেত্র: সেন্সর নোড {node_id} গত {minutes} মিনিট ধরে অফলাইন।"
        ),
        "depletion_warning": (
            "জলনেত্র: নোড {node_id}-এ ভূগর্ভস্থ জল {days} দিনের মধ্যে "
            "সংকটজনক স্তরে পৌঁছাবে বলে পূর্বাভাস।"
        ),
    },
    "mr": {
        "water_quality": (
            "जलनेत्र सूचना [{severity}]: नोड {node_id} वर पाणी गुणवत्ता समस्या. "
            "{parameter} = {value} {unit} (मर्यादा: {limit}). "
            "कृती: {action}"
        ),
        "battery_low": (
            "जलनेत्र: सेन्सर नोड {node_id} बॅटरी कमी ({battery}%). "
            "देखभालीचे नियोजन करा."
        ),
        "node_offline": (
            "जलनेत्र: सेन्सर नोड {node_id} गेल्या {minutes} मिनिटांपासून ऑफलाइन."
        ),
        "depletion_warning": (
            "जलनेत्र: नोड {node_id} वरील भूजल {days} दिवसांत "
            "गंभीर पातळीवर पोहोचण्याचा अंदाज."
        ),
    },
    "gu": {
        "water_quality": (
            "જલનેત્ર ચેતવણી [{severity}]: નોડ {node_id} પર પાણીની ગુણવત્તા સમસ્યા. "
            "{parameter} = {value} {unit} (મર્યાદા: {limit}). "
            "પગલું: {action}"
        ),
        "battery_low": (
            "જલનેત્ર: સેન્સર નોડ {node_id} બેટરી ઓછી ({battery}%). "
            "જાળવણી ગોઠવો."
        ),
        "node_offline": (
            "જલનેત્ર: સેન્સર નોડ {node_id} છેલ્લા {minutes} મિનિટથી ઓફલાઈન."
        ),
        "depletion_warning": (
            "જલનેત્ર: નોડ {node_id} પર ભૂગર્ભ જળ {days} દિવસમાં "
            "ગંભીર સ્તરે પહોંચશે એવી આગાહી."
        ),
    },
    "pa": {
        "water_quality": (
            "ਜਲਨੇਤਰ ਚੇਤਾਵਨੀ [{severity}]: ਨੋਡ {node_id} 'ਤੇ ਪਾਣੀ ਦੀ ਗੁਣਵੱਤਾ ਸਮੱਸਿਆ। "
            "{parameter} = {value} {unit} (ਸੀਮਾ: {limit})। "
            "ਕਾਰਵਾਈ: {action}"
        ),
        "battery_low": (
            "ਜਲਨੇਤਰ: ਸੈਂਸਰ ਨੋਡ {node_id} ਬੈਟਰੀ ਘੱਟ ({battery}%)। "
            "ਰੱਖ-ਰਖਾਅ ਦੀ ਯੋਜਨਾ ਬਣਾਓ।"
        ),
        "node_offline": (
            "ਜਲਨੇਤਰ: ਸੈਂਸਰ ਨੋਡ {node_id} ਪਿਛਲੇ {minutes} ਮਿੰਟਾਂ ਤੋਂ ਔਫਲਾਈਨ।"
        ),
        "depletion_warning": (
            "ਜਲਨੇਤਰ: ਨੋਡ {node_id} 'ਤੇ ਭੂਮੀਗਤ ਪਾਣੀ {days} ਦਿਨਾਂ ਵਿੱਚ "
            "ਗੰਭੀਰ ਪੱਧਰ 'ਤੇ ਪਹੁੰਚਣ ਦੀ ਭਵਿੱਖਬਾਣੀ।"
        ),
    },
}


# ---------------------------------------------------------------------------
# Channel routing rules
# ---------------------------------------------------------------------------

_CHANNEL_MAP: dict[AlertSeverity, list[str]] = {
    AlertSeverity.INFO: ["dashboard"],
    AlertSeverity.WARNING: ["sms", "dashboard"],
    AlertSeverity.CRITICAL: ["sms", "whatsapp", "dashboard"],
    AlertSeverity.EMERGENCY: ["sms", "whatsapp", "voice", "dashboard"],
}


# ---------------------------------------------------------------------------
# Subscriber model
# ---------------------------------------------------------------------------

@dataclass
class Subscriber:
    """A person who receives alerts."""

    subscriber_id: str
    name: str
    phone: str  # E.164 format, e.g. "+919876543210"
    language: str = "en"  # ISO 639-1
    whatsapp_id: str | None = None  # WhatsApp Business ID
    role: str = "farmer"  # farmer, panchayat, jjm_officer, technician
    node_subscriptions: set[int] = field(default_factory=set)  # empty = all nodes


# ---------------------------------------------------------------------------
# Alert record
# ---------------------------------------------------------------------------

@dataclass
class AlertRecord:
    """An individual alert that has been created and dispatched."""

    alert_id: str
    severity: AlertSeverity
    alert_type: str  # water_quality, battery_low, node_offline, depletion_warning
    node_id: int
    message: str
    language: str
    created_at: float
    channels_sent: list[str] = field(default_factory=list)
    channels_failed: list[str] = field(default_factory=list)
    acknowledged: bool = False
    acknowledged_at: float | None = None
    acknowledged_by: str | None = None
    escalated: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity.name,
            "alert_type": self.alert_type,
            "node_id": self.node_id,
            "message": self.message,
            "language": self.language,
            "created_at": self.created_at,
            "channels_sent": self.channels_sent,
            "channels_failed": self.channels_failed,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
            "escalated": self.escalated,
        }


# ---------------------------------------------------------------------------
# Async Alert Dispatcher
# ---------------------------------------------------------------------------

class AsyncAlertDispatcher:
    """Multi-channel alert dispatcher with deduplication, rate limiting,
    and acknowledgment-based escalation.

    Usage::

        dispatcher = AsyncAlertDispatcher(
            msg91_auth_key="...",
            msg91_sender_id="JALNET",
            whatsapp_api_url="https://...",
            whatsapp_api_token="...",
            twilio_account_sid="...",
            twilio_auth_token="...",
            bhashini_api_key="...",
        )
        await dispatcher.start()
        await dispatcher.dispatch_alert(
            severity=AlertSeverity.CRITICAL,
            alert_type="water_quality",
            node_id=3,
            parameters={"parameter": "TDS", "value": "2100", "unit": "ppm",
                        "limit": "2000", "action": "Do not use for drinking"},
        )
        await dispatcher.stop()
    """

    # -- Configuration constants ---
    DEDUP_WINDOW_SEC: float = 3600.0  # 1 hour
    RATE_LIMIT_PER_DAY: int = 10
    ESCALATION_TIMEOUT_SEC: dict[AlertSeverity, float] = {
        AlertSeverity.WARNING: 1800.0,   # 30 min
        AlertSeverity.CRITICAL: 600.0,   # 10 min
        AlertSeverity.EMERGENCY: 180.0,  # 3 min
    }
    HTTP_TIMEOUT_SEC: float = 30.0
    HTTP_MAX_RETRIES: int = 3

    def __init__(
        self,
        *,
        msg91_auth_key: str = "",
        msg91_sender_id: str = "JALNET",
        msg91_template_id: str = "",
        whatsapp_api_url: str = "",
        whatsapp_api_token: str = "",
        twilio_account_sid: str = "",
        twilio_auth_token: str = "",
        twilio_from_number: str = "",
        bhashini_api_key: str = "",
        bhashini_api_url: str = "https://dhruva-api.bhashini.gov.in",
        subscribers: list[Subscriber] | None = None,
        dashboard_callback: Any | None = None,
    ) -> None:
        # API credentials
        self._msg91_auth_key = msg91_auth_key
        self._msg91_sender_id = msg91_sender_id
        self._msg91_template_id = msg91_template_id
        self._whatsapp_api_url = whatsapp_api_url
        self._whatsapp_api_token = whatsapp_api_token
        self._twilio_sid = twilio_account_sid
        self._twilio_token = twilio_auth_token
        self._twilio_from = twilio_from_number
        self._bhashini_key = bhashini_api_key
        self._bhashini_url = bhashini_api_url

        # Subscribers
        self._subscribers: dict[str, Subscriber] = {}
        if subscribers:
            for sub in subscribers:
                self._subscribers[sub.subscriber_id] = sub

        # Dashboard push callback (e.g., WebSocket broadcast)
        self._dashboard_callback = dashboard_callback

        # Deduplication: hash -> timestamp of last dispatch
        self._dedup_cache: dict[str, float] = {}

        # Rate limiting: subscriber_id -> list of timestamps today
        self._rate_tracker: dict[str, list[float]] = {}

        # Alert history
        self._alerts: dict[str, AlertRecord] = {}

        # Escalation tracking
        self._pending_ack: dict[str, AlertRecord] = {}

        # Background tasks
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._http_client: httpx.AsyncClient | None = None

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Initialize HTTP client and start escalation monitor."""
        if self._running:
            return
        self._running = True
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.HTTP_TIMEOUT_SEC),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
        escalation_task = asyncio.create_task(
            self._escalation_monitor(),
            name="alert-escalation-monitor",
        )
        self._tasks.append(escalation_task)
        logger.info("Alert dispatcher started with %d subscribers", len(self._subscribers))

    async def stop(self) -> None:
        """Shut down cleanly."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Alert dispatcher stopped")

    # -- Subscriber management ----------------------------------------------

    def add_subscriber(self, subscriber: Subscriber) -> None:
        self._subscribers[subscriber.subscriber_id] = subscriber

    def remove_subscriber(self, subscriber_id: str) -> None:
        self._subscribers.pop(subscriber_id, None)

    # -- Main dispatch entry point ------------------------------------------

    async def dispatch_alert(
        self,
        *,
        severity: AlertSeverity,
        alert_type: str,
        node_id: int,
        parameters: dict[str, Any] | None = None,
        language: str | None = None,
    ) -> AlertRecord | None:
        """Create and dispatch an alert through all appropriate channels.

        Returns the ``AlertRecord`` if dispatched, or ``None`` if
        deduplicated/rate-limited.
        """
        params = parameters or {}

        # Build dedup key from severity + type + node + key parameters
        dedup_material = f"{severity.name}:{alert_type}:{node_id}:{sorted(params.items())}"
        dedup_hash = hashlib.sha256(dedup_material.encode()).hexdigest()[:16]

        # Deduplication check
        now = time.time()
        last_sent = self._dedup_cache.get(dedup_hash, 0.0)
        if now - last_sent < self.DEDUP_WINDOW_SEC:
            logger.debug(
                "Alert deduplicated (hash=%s, last sent %.0fs ago)",
                dedup_hash,
                now - last_sent,
            )
            return None
        self._dedup_cache[dedup_hash] = now

        # Clean stale dedup entries (older than 2 hours)
        stale = [k for k, v in self._dedup_cache.items() if now - v > 7200]
        for k in stale:
            del self._dedup_cache[k]

        # Determine language (default from first relevant subscriber, fallback to English)
        lang = language or "en"

        # Build message from template
        message = self._render_template(alert_type, lang, severity, params)

        # Create alert record
        alert = AlertRecord(
            alert_id=str(uuid.uuid4()),
            severity=severity,
            alert_type=alert_type,
            node_id=node_id,
            message=message,
            language=lang,
            created_at=now,
            parameters=params,
        )
        self._alerts[alert.alert_id] = alert

        # Get channels for this severity
        channels = _CHANNEL_MAP.get(severity, ["dashboard"])

        # Dispatch to each channel
        for channel in channels:
            try:
                if channel == "dashboard":
                    await self._send_dashboard(alert)
                    alert.channels_sent.append("dashboard")
                elif channel == "sms":
                    await self._send_sms_to_subscribers(alert)
                    alert.channels_sent.append("sms")
                elif channel == "whatsapp":
                    await self._send_whatsapp_to_subscribers(alert)
                    alert.channels_sent.append("whatsapp")
                elif channel == "voice":
                    await self._send_voice_to_subscribers(alert)
                    alert.channels_sent.append("voice")
            except Exception:
                logger.exception("Failed to dispatch via channel %s", channel)
                alert.channels_failed.append(channel)

        # Track for acknowledgment-based escalation (skip INFO)
        if severity >= AlertSeverity.WARNING:
            self._pending_ack[alert.alert_id] = alert

        logger.info(
            "Alert dispatched: id=%s severity=%s type=%s node=%d channels=%s",
            alert.alert_id,
            severity.name,
            alert_type,
            node_id,
            alert.channels_sent,
        )
        return alert

    # -- Acknowledgment -----------------------------------------------------

    async def acknowledge_alert(
        self, alert_id: str, acknowledged_by: str
    ) -> bool:
        """Mark an alert as acknowledged. Returns True if found."""
        alert = self._alerts.get(alert_id)
        if not alert:
            return False
        alert.acknowledged = True
        alert.acknowledged_at = time.time()
        alert.acknowledged_by = acknowledged_by
        self._pending_ack.pop(alert_id, None)
        logger.info("Alert %s acknowledged by %s", alert_id, acknowledged_by)
        return True

    # -- Template rendering -------------------------------------------------

    def _render_template(
        self,
        alert_type: str,
        language: str,
        severity: AlertSeverity,
        params: dict[str, Any],
    ) -> str:
        lang_templates = ALERT_TEMPLATES.get(language, ALERT_TEMPLATES["en"])
        template = lang_templates.get(alert_type)
        if not template:
            # Fallback to English
            template = ALERT_TEMPLATES["en"].get(
                alert_type,
                "JalNetra Alert: {severity} at Node {node_id}",
            )
        try:
            return template.format(severity=severity.name, **params)
        except KeyError as exc:
            logger.warning("Template render error (missing key %s), using raw", exc)
            return f"JalNetra {severity.name}: {alert_type} at node (params: {params})"

    # -- Rate limiting ------------------------------------------------------

    def _check_rate_limit(self, subscriber_id: str) -> bool:
        """Return True if the subscriber is within daily rate limits."""
        now = time.time()
        day_start = now - (now % 86400)  # midnight UTC today

        history = self._rate_tracker.get(subscriber_id, [])
        # Prune entries from previous days
        history = [t for t in history if t >= day_start]
        self._rate_tracker[subscriber_id] = history

        if len(history) >= self.RATE_LIMIT_PER_DAY:
            logger.warning(
                "Rate limit hit for subscriber %s (%d/%d today)",
                subscriber_id,
                len(history),
                self.RATE_LIMIT_PER_DAY,
            )
            return False
        return True

    def _record_send(self, subscriber_id: str) -> None:
        self._rate_tracker.setdefault(subscriber_id, []).append(time.time())

    # -- Channel: Dashboard -------------------------------------------------

    async def _send_dashboard(self, alert: AlertRecord) -> None:
        """Push alert to dashboard via callback (typically WebSocket broadcast)."""
        if self._dashboard_callback:
            try:
                result = self._dashboard_callback(alert.to_dict())
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Dashboard callback failed for alert %s", alert.alert_id)
        logger.debug("Dashboard alert pushed: %s", alert.alert_id)

    # -- Channel: SMS via MSG91 ---------------------------------------------

    async def _send_sms_to_subscribers(self, alert: AlertRecord) -> None:
        """Send SMS to all relevant subscribers via MSG91."""
        for sub in self._get_relevant_subscribers(alert.node_id):
            if not self._check_rate_limit(sub.subscriber_id):
                continue

            # Render in subscriber's language
            message = self._render_template(
                alert.alert_type, sub.language, alert.severity, alert.parameters
            )
            await self._send_sms(sub.phone, message)
            self._record_send(sub.subscriber_id)

    async def _send_sms(self, phone: str, message: str) -> None:
        """Send a single SMS via MSG91 API."""
        if not self._msg91_auth_key:
            logger.debug("SMS skipped (no MSG91 auth key): %s -> %s...", phone, message[:50])
            return

        url = "https://control.msg91.com/api/v5/flow/"
        headers = {"authkey": self._msg91_auth_key, "Content-Type": "application/json"}
        payload = {
            "template_id": self._msg91_template_id,
            "sender": self._msg91_sender_id,
            "short_url": "0",
            "mobiles": phone.lstrip("+"),
            "var1": message[:160],  # MSG91 template variable
        }

        await self._http_request_with_retry("POST", url, headers=headers, json=payload)
        logger.info("SMS sent to %s", phone)

    # -- Channel: WhatsApp via Business API ---------------------------------

    async def _send_whatsapp_to_subscribers(self, alert: AlertRecord) -> None:
        """Send WhatsApp messages to relevant subscribers."""
        for sub in self._get_relevant_subscribers(alert.node_id):
            if not sub.whatsapp_id and not sub.phone:
                continue
            if not self._check_rate_limit(sub.subscriber_id):
                continue

            message = self._render_template(
                alert.alert_type, sub.language, alert.severity, alert.parameters
            )
            recipient = sub.whatsapp_id or sub.phone
            await self._send_whatsapp(recipient, message)
            self._record_send(sub.subscriber_id)

    async def _send_whatsapp(self, recipient: str, message: str) -> None:
        """Send a single WhatsApp message via Business API."""
        if not self._whatsapp_api_url or not self._whatsapp_api_token:
            logger.debug(
                "WhatsApp skipped (no config): %s -> %s...", recipient, message[:50]
            )
            return

        url = f"{self._whatsapp_api_url}/v1/messages"
        headers = {
            "Authorization": f"Bearer {self._whatsapp_api_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": message},
        }

        await self._http_request_with_retry("POST", url, headers=headers, json=payload)
        logger.info("WhatsApp message sent to %s", recipient)

    # -- Channel: Voice via Bhashini TTS + Twilio ---------------------------

    async def _send_voice_to_subscribers(self, alert: AlertRecord) -> None:
        """Generate TTS audio via Bhashini and place voice calls via Twilio."""
        for sub in self._get_relevant_subscribers(alert.node_id):
            if not self._check_rate_limit(sub.subscriber_id):
                continue

            message = self._render_template(
                alert.alert_type, sub.language, alert.severity, alert.parameters
            )
            await self._send_voice_call(sub.phone, message, sub.language)
            self._record_send(sub.subscriber_id)

    async def _send_voice_call(
        self, phone: str, message: str, language: str
    ) -> None:
        """Generate speech via Bhashini TTS and call via Twilio."""
        if not self._twilio_sid or not self._bhashini_key:
            logger.debug(
                "Voice call skipped (no Twilio/Bhashini config): %s", phone
            )
            return

        # Step 1: Generate TTS audio URL via Bhashini
        tts_url = await self._bhashini_tts(message, language)
        if not tts_url:
            logger.error("Bhashini TTS failed for language %s, skipping voice call", language)
            return

        # Step 2: Place call via Twilio using TwiML that plays the audio
        twiml = (
            f'<Response><Play>{tts_url}</Play>'
            f'<Pause length="1"/>'
            f'<Play>{tts_url}</Play></Response>'
        )

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._twilio_sid}/Calls.json"
        auth = (self._twilio_sid, self._twilio_token)
        data = {
            "To": phone,
            "From": self._twilio_from,
            "Twiml": twiml,
        }

        if self._http_client:
            resp = await self._http_client.post(url, data=data, auth=auth)
            if resp.status_code < 300:
                logger.info("Voice call initiated to %s", phone)
            else:
                logger.error(
                    "Twilio call failed: %d %s", resp.status_code, resp.text[:200]
                )

    async def _bhashini_tts(self, text: str, language: str) -> str | None:
        """Convert text to speech via Bhashini Dhruva API. Returns audio URL."""
        # Map ISO 639-1 to Bhashini language codes
        lang_map = {
            "hi": "hi", "en": "en", "ta": "ta", "te": "te",
            "kn": "kn", "ml": "ml", "bn": "bn", "mr": "mr",
            "gu": "gu", "pa": "pa",
        }
        bhashini_lang = lang_map.get(language, "en")

        url = f"{self._bhashini_url}/services/inference/pipeline"
        headers = {
            "Authorization": self._bhashini_key,
            "Content-Type": "application/json",
        }
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": bhashini_lang},
                        "gender": "female",
                    },
                }
            ],
            "inputData": {"input": [{"source": text}]},
        }

        try:
            resp_data = await self._http_request_with_retry(
                "POST", url, headers=headers, json=payload
            )
            if resp_data and isinstance(resp_data, dict):
                audio_content = (
                    resp_data.get("pipelineResponse", [{}])[0]
                    .get("audio", [{}])[0]
                    .get("audioUri", "")
                )
                return audio_content or None
        except Exception:
            logger.exception("Bhashini TTS request failed")
        return None

    # -- Subscriber filtering -----------------------------------------------

    def _get_relevant_subscribers(self, node_id: int) -> list[Subscriber]:
        """Return subscribers interested in alerts from the given node."""
        relevant = []
        for sub in self._subscribers.values():
            if not sub.node_subscriptions or node_id in sub.node_subscriptions:
                relevant.append(sub)
        return relevant

    # -- HTTP helper with retry ---------------------------------------------

    async def _http_request_with_retry(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any] | None:
        """Make an HTTP request with exponential backoff retry."""
        retries = max_retries or self.HTTP_MAX_RETRIES
        if not self._http_client:
            logger.error("HTTP client not initialized -- call start() first")
            return None

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = await self._http_client.request(
                    method, url, headers=headers, json=json
                )
                resp.raise_for_status()
                try:
                    return resp.json()
                except Exception:
                    return None
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                wait = min(2 ** attempt, 30)
                logger.warning(
                    "HTTP %s %s attempt %d/%d failed: %s -- retrying in %ds",
                    method, url, attempt + 1, retries, exc, wait,
                )
                await asyncio.sleep(wait)

        logger.error(
            "HTTP %s %s failed after %d retries: %s", method, url, retries, last_exc
        )
        return None

    # -- Escalation monitor -------------------------------------------------

    async def _escalation_monitor(self) -> None:
        """Background task that escalates unacknowledged alerts."""
        while self._running:
            try:
                now = time.time()
                to_escalate: list[AlertRecord] = []

                for alert_id, alert in list(self._pending_ack.items()):
                    if alert.acknowledged:
                        self._pending_ack.pop(alert_id, None)
                        continue

                    timeout = self.ESCALATION_TIMEOUT_SEC.get(alert.severity)
                    if timeout and (now - alert.created_at) > timeout and not alert.escalated:
                        to_escalate.append(alert)

                for alert in to_escalate:
                    await self._escalate_alert(alert)

                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Escalation monitor error")
                await asyncio.sleep(5)

    async def _escalate_alert(self, alert: AlertRecord) -> None:
        """Escalate an unacknowledged alert to the next severity level."""
        alert.escalated = True
        next_severity = AlertSeverity(
            min(alert.severity + 1, AlertSeverity.EMERGENCY)
        )
        logger.warning(
            "Escalating alert %s from %s to %s (unacknowledged for %.0fs)",
            alert.alert_id,
            alert.severity.name,
            next_severity.name,
            time.time() - alert.created_at,
        )

        # Re-dispatch at higher severity
        await self.dispatch_alert(
            severity=next_severity,
            alert_type=alert.alert_type,
            node_id=alert.node_id,
            parameters={**alert.parameters, "escalated_from": alert.alert_id},
            language=alert.language,
        )

    # -- Query API ----------------------------------------------------------

    def get_alert(self, alert_id: str) -> AlertRecord | None:
        return self._alerts.get(alert_id)

    def get_recent_alerts(
        self, *, limit: int = 50, severity: AlertSeverity | None = None
    ) -> list[AlertRecord]:
        alerts = sorted(
            self._alerts.values(), key=lambda a: a.created_at, reverse=True
        )
        if severity is not None:
            alerts = [a for a in alerts if a.severity >= severity]
        return alerts[:limit]

    @property
    def stats(self) -> dict[str, Any]:
        now = time.time()
        day_start = now - (now % 86400)
        today_alerts = [a for a in self._alerts.values() if a.created_at >= day_start]
        return {
            "total_alerts": len(self._alerts),
            "today_alerts": len(today_alerts),
            "pending_ack": len(self._pending_ack),
            "subscribers": len(self._subscribers),
            "dedup_cache_size": len(self._dedup_cache),
            "severity_counts": {
                sev.name: sum(
                    1 for a in self._alerts.values() if a.severity == sev
                )
                for sev in AlertSeverity
            },
        }
