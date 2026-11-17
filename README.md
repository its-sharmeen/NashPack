# NaShPack – AI-Powered Legal Metrology Compliance Checker

**An AI-powered solution for automating packaged commodity compliance inspections under the Legal Metrology (Packaged Commodities) Rules, 2011.**

## Overview

NaShPack is a smart compliance-checking system designed to assist Legal Metrology officers in inspecting packaged commodities. It uses a Vision Language Model (VLM) to analyze product packaging, identify mandatory declarations, and help detect missing or potentially non-compliant information.

The system aims to make the inspection process faster, more consistent, and easier to document through AI-powered image analysis and Augmented Reality (AR)-based measurement.

## Key Features

- **Secure Officer Login:** Individual officer accounts with separate inspection records.
- **AI-Powered Package Analysis:** Uses Google's Gemini Vision Language Model to analyze product packaging.
- **Mandatory Declaration Verification:** Checks important packaged commodity declarations.
- **Non-Compliance Detection:** Highlights missing or potentially non-compliant information.
- **Visual Annotations:** Helps officers identify relevant information on package images.
- **AR-Based Measurement:** Supports measurement of package dimensions and declaration details in millimetres (mm).
- **Compliance Dashboard:** Provides an overview of inspection activity and results.
- **Inspection History:** Maintains records of previous inspections.
- **Report Generation:** Supports downloadable inspection reports in PDF and CSV formats.

## Technology Stack

| Component       | Technology              |
| --------------- | ----------------------- |
| Backend         | Python, Flask           |
| AI / Vision     | Google Gemini API (VLM) |
| Frontend        | HTML, CSS, JavaScript   |
| Measurement     | Augmented Reality (AR)  |
| Data Processing | Python                  |

## How It Works

1. **Login:** The officer signs in using their account.
2. **Upload Image:** An image of the packaged commodity is uploaded or captured.
3. **AI Analysis:** Gemini VLM analyzes the package image.
4. **Declaration Verification:** The system checks the required declarations.
5. **Visual Identification:** Relevant details and potential issues are highlighted.
6. **AR Measurement:** The officer can use AR-based measurement functionality to measure relevant dimensions.
7. **Compliance Report:** The system presents the inspection result and allows report export.

## Installation and Setup

### Prerequisites

- Python 3.11 or compatible version
- pip
- Google Gemini API key

### 1. Clone the Repository

```bash
git clone https://github.com/its-sharmeen/NaShPack.git
cd NaShPack
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root and add your Gemini API key using the environment variable name expected by your application.

```env
GEMINI_API_KEY=your_api_key_here
```

**Important:** Never upload your `.env` file or expose your API key publicly.

### 5. Run the Application

```bash
python app.py
```

Open your browser and visit:

```text
http://127.0.0.1:5000
```

*The startup command and environment variable name should match your actual project configuration.*

## Project Structure

```text
NaShPack/
│
├── app.py
├── requirements.txt
├── .env
├── .gitignore
│
├── static/
│   ├── css/
│   ├── js/
│   └── images/
│
├── templates/
│
└── README.md
```

*The structure above is illustrative. Your actual folders may differ.*

## Project Objective

To improve the efficiency of packaged commodity inspections by combining AI-based visual analysis, automated declaration verification, and AR-based measurement in a single platform for Legal Metrology officers.

## Future Scope

- Improved detection accuracy across different packaging types.
- Support for additional product categories and declaration rules.
- Enhanced AR measurement precision and usability.
- Integration with centralized inspection and reporting systems.

## Contributors

**NaShPack Project Team**

Developed as a technology-driven solution for Legal Metrology compliance inspection.

---

**Disclaimer:** NaShPack is an assistive compliance-checking tool. Final regulatory decisions should be made by authorized Legal Metrology officers based on applicable rules and verification.
