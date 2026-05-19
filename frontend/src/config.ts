// API base URL — set VITE_API_URL in your Vercel environment variables
// pointing to your Render backend URL e.g. https://ai-governance-api.onrender.com
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default API_URL;
