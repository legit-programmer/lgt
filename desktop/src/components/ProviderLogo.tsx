import { Terminal } from "lucide-react";
import claude from "../assets/providers/claude.svg";
import gemini from "../assets/providers/gemini.svg";
import "./ProviderLogo.css";

/** Decorative provider identity; the adjacent text supplies the accessible name. */
export function ProviderLogo({ harness }: { harness: string }) {
  if (harness === "codex") return <span className="fv-provider-logo fv-provider-logo--codex" aria-hidden="true" />;
  const source = harness === "claude" || harness === "claude_code" ? claude : harness === "gemini" ? gemini : null;
  return source
    ? <img className="fv-provider-logo" src={source} alt="" aria-hidden="true" />
    : <Terminal className="fv-provider-logo" aria-hidden="true" />;
}
