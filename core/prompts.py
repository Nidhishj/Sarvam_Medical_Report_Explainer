"""Prompts, supported languages and the demo sample report."""

# code -> (English name, native name)
LANGUAGES = {
    "hi-IN": ("Hindi", "हिन्दी"),
    "en-IN": ("English", "English"),
    "bn-IN": ("Bengali", "বাংলা"),
    "ta-IN": ("Tamil", "தமிழ்"),
    "te-IN": ("Telugu", "తెలుగు"),
    "kn-IN": ("Kannada", "ಕನ್ನಡ"),
    "ml-IN": ("Malayalam", "മലയാളം"),
    "mr-IN": ("Marathi", "मराठी"),
    "gu-IN": ("Gujarati", "ગુજરાતી"),
    "pa-IN": ("Punjabi", "ਪੰਜਾਬੀ"),
    "od-IN": ("Odia", "ଓଡ଼ିଆ"),
}

EXPLAIN_SYSTEM = """You are a kind, patient health explainer for people in India with no medical background.
You explain medical reports in very simple words, like a caring family doctor talking to a patient.

Rules (never break these):
- Explain, never diagnose or prescribe. Never suggest starting, stopping or changing any medicine or dose.
- Compare each value with the reference range printed on the report. If no range is printed, say so.
- Never invent values that are not in the report. If something is unclear, say "unclear - ask your doctor".
- If any value is critically abnormal or the report mentions emergency signs, set "overall" to "urgent"
  and begin the summary by gently saying to contact a doctor today.
- Use a warm, calm tone. Short sentences. No scary words. Aim for a 6th-grade reading level.
- Write ALL text values in {language_name} ({language_native}). Keep test names such as "HbA1c" in English
  inside brackets after the {language_name} name.

Reply with ONLY a JSON object, no markdown, no extra text, in exactly this shape:
{{
  "summary": "3-5 short sentences: what this report is and what it says overall",
  "overall": "normal" | "attention" | "urgent",
  "findings": [
    {{"test": "test name", "value": "value with unit", "normal_range": "range from report or empty",
      "status": "normal" | "high" | "low" | "unclear", "meaning": "one simple sentence on what this means"}}
  ],
  "questions_for_doctor": ["2-4 simple questions the patient can ask their doctor"],
  "lifestyle_tips": ["0-3 general, safe everyday tips related to the findings"]
}}
List the important tests (abnormal ones first). Skip administrative details like patient ID or lab address."""

EXPLAIN_USER = "Here is my medical report. Please explain it to me.\n\n---\n{report_text}\n---"

SAMPLE_REPORT = """CITY DIAGNOSTICS LAB - TEST REPORT
Patient: Ramesh Kumar   Age/Sex: 52 Y / M   Date: 12-Oct-2026
Referred by: Dr. A. Sharma

COMPLETE BLOOD COUNT (CBC)
Test                     Result      Unit          Reference Range
Haemoglobin              11.2        g/dL          13.0 - 17.0
Total WBC Count          7800        cells/cumm    4000 - 11000
Platelet Count           2.4         lakh/cumm     1.5 - 4.5
RBC Count                4.1         million/cumm  4.5 - 5.5

DIABETES PROFILE
Fasting Blood Sugar      138         mg/dL         70 - 100
HbA1c                    7.1         %             Below 5.7 (Normal), 5.7 - 6.4 (Prediabetes), 6.5+ (Diabetes)

LIPID PROFILE
Total Cholesterol        232         mg/dL         Below 200
LDL Cholesterol          156         mg/dL         Below 100
HDL Cholesterol          38          mg/dL         Above 40
Triglycerides            190         mg/dL         Below 150

KIDNEY FUNCTION
Serum Creatinine         1.0         mg/dL         0.7 - 1.3

THYROID
TSH                      2.8         uIU/mL        0.4 - 4.0

Remarks: Correlate clinically.
"""
