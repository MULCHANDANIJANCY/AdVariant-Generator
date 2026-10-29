import json, re
from http.server import BaseHTTPRequestHandler
from google import genai
from google.genai import types

_client = genai.Client()  # reads GEMINI_API_KEY automatically


def ask(system, user, tokens=2000):
    r = _client.models.generate_content(
        model="gemini-2.5-flash", contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json",
            max_output_tokens=tokens, thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return json.loads(r.text)


RISKY = [
    (r"\bguarantee[sd]?\b", "Guarantee claim: needs written terms and approval"),
    (r"\b(cure[sd]?|treats?|heals?|prevents?)\b", "Possible health claim: needs legal and medical review"),
    (r"(#1|\bnumber one\b|\bbest\b|\bleading\b|\bworld['’]s\b)", "Superlative or ranking: needs substantiation"),
    (r"(\brisk[- ]free\b|\bno risk\b|100%)", "Absolute claim: needs substantiation"),
    (r"\b(clinically proven|scientifically proven|proven to)\b", "Proof claim: needs a citable study"),
    (r"\bfree\b", "“Free” offer: must match the offer terms exactly"),
    (r"\b(limited time|ends soon|hurry|last chance)\b", "Urgency claim: needs a real end date"),
    (r"(before and after|\blose \d+|\bearn \$?\d+|\bmake \$?\d+)", "Result or earnings claim: needs substantiation and disclaimers"),
]
SYSTEM = """You are a senior performance-marketing strategist writing for human review.
Rules:
- Use ONLY facts in the brief. Never invent statistics, prices, awards, testimonials, customer names or guarantees.
- If a strong ad would need a proof point you were not given, put it in required_proof as something the human must supply, and do not state it in the copy.
- Obey the brand tone and never use the banned words.
- Each variant must use a different angle (for example: pain point, outcome, social proof request, offer-led, curiosity, comparison).
- hook is one line. body is 1 to 3 short sentences. cta is 2 to 5 words.
- warnings: list anything risky or unverifiable in that variant.
Return ONLY JSON: {"brief":{"objective":"","audience_insight":"","key_message":"","tone":"","proof_needed":[""]},"variants":[{"angle":"","hook":"","body":"","cta":"","required_proof":[""],"warnings":[""]}]}"""


class handler(BaseHTTPRequestHandler):
    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("content-length", 0) or 0)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "Invalid JSON"})
        if not d.get("product") or not d.get("audience"):
            return self.send(400, {"error": "Product and audience are required."})
        try:
            n = min(max(int(d.get("count") or 4), 2), 6)
        except ValueError:
            n = 4
        banned = [w.strip().lower() for w in str(d.get("banned", "")).split(",") if w.strip()]
        try:
            user = json.dumps({"product": d["product"], "audience": d["audience"], "offer": d.get("offer") or "none", "channel": d.get("channel") or "social",
                               "tone": d.get("tone") or "clear and professional", "bannedWords": banned, "variants": n})
            ai = ask(SYSTEM, user, 3000)
            source = json.dumps(d).lower()
            out = []
            for v in ai.get("variants", [])[:n]:
                copy = f'{v.get("hook", "")} {v.get("body", "")} {v.get("cta", "")}'
                found = []
                for pat, msg in RISKY:
                    mm = re.search(pat, copy, re.I)
                    if mm:
                        found.append(f"{msg} (“{mm.group(0)}”)")
                for w in banned:
                    if w in copy.lower():
                        found.append(f"Banned word used: “{w}”")
                for x in re.findall(r"\d[\d,.]*\s?%?", copy):
                    x = x.strip().rstrip(".,")
                    if x and x.lower() not in source:
                        found.append(f"Number “{x}” is not in your brief, so it may be invented")
                if len(v.get("cta", "").split()) > 6:
                    found.append("CTA is long")
                out.append({**v, "checks": found, "status": "Pending approval"})
            ai["variants"] = out
            self.send(200, ai)
        except Exception as e:
            self.send(500, {"error": str(e)})