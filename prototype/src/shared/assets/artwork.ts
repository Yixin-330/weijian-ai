

export function appearanceThemeKey(appearance?: string) {
  if (appearance === "晨光") return "dawn";
  if (appearance === "流金") return "gold";
  return "mist";
}

export function lifeformPortraitSrc(appearance?: string) {
  const theme = appearanceThemeKey(appearance);
  if (theme === "dawn") return "/assets/wj/wj-desktop-lifeform-portrait-dawn-v1.png";
  if (theme === "gold") return "/assets/wj/wj-desktop-lifeform-portrait-gold-v1.png";
  return "/assets/wj/wj-desktop-lifeform-portrait-v1.png";
}

export function worldArtworkSrc(appearance?: string) {
  const theme = appearanceThemeKey(appearance);
  if (theme === "dawn") return "/assets/wj/wj-desktop-world-dawn-v1.png";
  if (theme === "gold") return "/assets/wj/wj-desktop-world-gold-v1.png";
  return "/assets/wj/wj-desktop-world-immersive-v1.png";
}
