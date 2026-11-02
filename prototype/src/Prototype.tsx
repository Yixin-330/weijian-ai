import { DesktopPrototype } from "./app/DesktopApp";
import { MobilePrototype } from "./app/MobileApp";

export default function Prototype() {
  const desktopMode = window.location.pathname.startsWith("/demo") || new URLSearchParams(window.location.search).get("mode") === "desktop";
  return desktopMode ? <DesktopPrototype /> : <MobilePrototype />;
}
