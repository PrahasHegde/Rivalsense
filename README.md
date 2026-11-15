RivalSense — AI-Powered Web Intelligence

<strong>A clearer view. A smarter next move.</strong>

AI-powered market research, competitive intelligence, and product analysis — all in one workspace.

🚀 Overview

RivalSense is an AI-powered web intelligence platform built for Junction 2026. It simplifies online research by bringing information from company websites, articles, and product listings into a unified research workspace.

Instead of manually navigating dozens of browser tabs, users can ask questions in natural language, explore AI-generated answers, inspect original sources, and compare competitor products.

RivalSense combines three capabilities:

AI Research: Ask questions about companies, markets, and competitive landscapes.
Product Intelligence: Extract and compare product information from publicly accessible URLs.
Financial Simulation: Model pricing scenarios and estimate their potential financial impact.

The goal is simple: reduce fragmented research and help people make smarter, evidence-backed decisions.

✨ Features

1. AI-Powered Web Research

Ask questions in natural language and receive structured answers backed by web research.

Research companies, industries, and markets.
Explore competitive landscapes.
Use suggested research questions or enter custom queries.
Access the original sources behind generated answers.
Inspect citations to verify individual claims.
Preserve retrieved answers, citations, and observation timestamps.

Example:

Who founded Microsoft and in what year?

RivalSense identifies Bill Gates and Paul Allen as Microsoft's founders and 1975 as its founding year, with a source citation linking to the relevant historical information.

2. Competitor Product Intelligence

Research and compare products using their publicly accessible product URLs.

Submit a reference product URL.
Extract product information from the original webpage.
Add competitor product URLs for comparison.
View extracted information alongside its original source.
Preserve observation timestamps.
Compare products using confirmed identities and matching currencies.
Keep uncertain product matches separate instead of presenting unsupported comparisons.

This helps businesses monitor competitor offerings and understand differences in product positioning and pricing.

3. Financial Scenario Simulator

Evaluate the potential impact of different pricing and cost assumptions.

Enter:

Selling price per unit.
Cost per unit.
Number of units sold.

RivalSense calculates estimated gross profit.

Example calculation:

Parameter Value
Selling price €20
Cost per unit €12
Units sold 100
Revenue €2,000
Total cost €1,200
Gross profit €800

Formula:

Gross Profit = (Selling Price - Cost Per Unit) × Units Sold

4. Source Transparency and Research History

RivalSense emphasizes verifiable research rather than unsubstantiated AI-generated claims.

Access clickable source citations.
Inspect the original webpages behind research results.
Preserve original answers and their citations.
View when information was retrieved.
Distinguish saved research context from live information. 5. Authentication and User Sessions
Google sign-in through Supabase.
Authenticated application requests.
User session management.
Server-side handling of third-party provider credentials.
🛠️ Technology Stack

RivalSense uses a modern frontend/backend architecture.

Component Technology Responsibility
Frontend React User interface and research workspace
Backend FastAPI API endpoints, request validation, and research orchestration
Web Intelligence Context.dev Web information retrieval and source citations
Authentication Supabase Google sign-in and session management
Communication HTTP API Frontend-to-backend communication
Deployment Unified web service Frontend and API deployment
Architecture

The application follows a client-server architecture:

mermaid
flowchart TD
U[User] --> FE[React Frontend]
FE --> AUTH[Supabase Authentication]
FE --> API[FastAPI Backend]
API --> VALID[Request Validation]
VALID --> RESEARCH[Research Orchestration]
RESEARCH --> CTX[Context.dev]
CTX --> RESULTS[Answers and Source Citations]
RESULTS --> API
API --> FE
FE --> USER[Research Results]

Request flow:

Users interact with the React frontend.
Supabase manages authentication and user sessions.
The frontend sends authenticated requests to the FastAPI backend.
The backend validates requests and coordinates research operations.
Context.dev retrieves relevant web information and returns answers with source citations.
The backend delivers the results to the frontend.
Users explore the answers and inspect their original sources.

Third-party provider credentials remain on the server rather than being exposed in the browser.

The frontend and API are deployed together as a unified web service.

📂 Repository Structure

The repository is organized into separate frontend and backend applications.

text
Rivalsense/
│
├── Backend/
│ └── Backend source code and API implementation
│
├── frontEnd/
│ └── React frontend and user interface
│
├── .gitignore
├── .oxlintrc.json
└── README.md

Backend

Responsible for:

API request handling.
Authentication validation.
Research orchestration.
Context.dev integration.
Product information extraction and comparison.
Financial calculations.
Frontend

Responsible for:

Research dashboard and workspace.
Natural-language query interface.
Research result presentation.
Source citation navigation.
Competitor product comparison.
Financial scenario simulation.
Authentication interface.
⚙️ Getting Started
Prerequisites

Before running RivalSense locally, ensure you have:

Git
Node.js and npm (for the frontend)
Python 3 and pip (for the backend)
A Supabase project
Context.dev API credentials

1. Clone the Repository
   bash
   git clone https://github.com/PrahasHegde/Rivalsense.git

cd Rivalsense

2. Set Up the Backend

Navigate to the backend directory:

bash
cd Backend

Install the backend dependencies using the dependency manifest provided in the directory.

For a Python requirements-based setup:

bash
pip install -r requirements.txt

Configure the required backend environment variables using the project's environment template.

Start the backend using its configured development command.

3. Set Up the Frontend

Open another terminal and navigate to the frontend directory:

bash
cd Rivalsense/frontEnd

Install dependencies:

bash
npm install

Start the development server using the script defined in package.json.

4. Configure Environment Variables

Configure the necessary credentials for your deployment.

The application requires:

Supabase project configuration for authentication.
Context.dev credentials for web intelligence and research.

Security note: Keep API keys and secrets in backend environment variables. Never commit credentials or expose private provider keys in frontend code.

Refer to the backend and frontend configuration files for the exact variable names and requirements.

💡 Example Use Cases
User Use case
Businesses Research competitors and monitor product pricing
Researchers Investigate markets and trace claims to original sources
Entrepreneurs Evaluate product positioning and pricing strategies
Product Managers Compare competing products and offerings
Individuals Research companies and explore questions without losing their research trail
🎯 Why RivalSense?

Traditional online research often involves:

Opening multiple websites and browser tabs.
Manually collecting and comparing information.
Dealing with conflicting or outdated details.
Losing track of where information originated.
Repeating the same research for different decisions.

RivalSense brings these activities together into one intelligent workspace.

Our approach:

Ask better questions through natural-language research.
Get structured answers supported by web sources.
Compare competitor products using extracted information.
Evaluate financial scenarios before making decisions.
Follow the evidence instead of blindly trusting AI-generated answers.
🏆 Built for Junction 2026

RivalSense was developed as part of Junction 2026 with the vision of making web intelligence more accessible, transparent, and actionable.

The project brings together AI-powered research, competitive product intelligence, and financial decision support in a single application.

🔮 Future Scope

Potential areas for further development include:

Automated competitor price monitoring.
Historical product pricing and change tracking.
Advanced market and industry analysis.
Exportable research reports.
Multi-competitor comparison dashboards.
Research history and saved workspaces.
Automated alerts for competitor product changes.
More advanced financial forecasting and scenario analysis.
🔐 Security and Responsible Use
Keep third-party API credentials on the backend.
Use authenticated requests for protected application functionality.
Prefer publicly accessible product and information sources.
Verify original citations before relying on research findings.
Treat extracted web information as potentially incomplete or outdated.
👥 Contributors

Built by the RivalSense team for Junction 2026.

📺 Demo

Watch the RivalSense Junction 2026 demonstration:

Watch the project demo on YouTube

📦 Repository

GitHub — PrahasHegde/Rivalsense

<p align="center">
<strong>RivalSense</strong>
<br/>
Ask a better question. Follow the evidence. Make a smarter next move.
</p>
