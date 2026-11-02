

export const isStandaloneExperience = () => {
  if (import.meta.env.VITE_EXPERIENCE_MODE === "standalone") return true;
  if (import.meta.env.VITE_API_BASE_URL) return false;
  return !["127.0.0.1", "localhost"].includes(window.location.hostname);
};
