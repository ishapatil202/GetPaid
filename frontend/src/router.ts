import { useEffect, useState } from "react";

// Tiny hash router: #/, #/new, #/contracts/3, #/invoices
export function useRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash.replace(/^#/, "") || "/";
}

export function go(path: string) {
  window.location.hash = path;
}
