import { useEffect, useState } from "react";
import { api, getSession, setSession } from "./api";
import { go, useRoute } from "./router";
import Welcome from "./pages/Welcome";
import Contracts from "./pages/Contracts";
import NewContract from "./pages/NewContract";
import Review from "./pages/Review";
import Invoices from "./pages/Invoices";

export default function App() {
  const route = useRoute();
  const [session, setSessionState] = useState(getSession());
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);

  useEffect(() => {
    const onLogout = () => setSessionState(null);
    window.addEventListener("getpaid:logout", onLogout);
    return () => window.removeEventListener("getpaid:logout", onLogout);
  }, []);

  async function tryDemo() {
    setLoggingIn(true);
    setLoginError(null);
    try {
      const login = await api.demoLogin();
      setSession(login.token, login.name);
      setSessionState(getSession());
      go("/");
    } catch (error) {
      setLoginError((error as Error).message);
    } finally {
      setLoggingIn(false);
    }
  }

  function logOut() {
    setSession(null, null);
    setSessionState(null);
    go("/");
  }

  if (!session) {
    return <Welcome onTryDemo={tryDemo} loading={loggingIn} error={loginError} />;
  }

  const contractMatch = route.match(/^\/contracts\/(\d+)$/);
  let page;
  if (route === "/new") page = <NewContract />;
  else if (contractMatch) page = <Review contractId={Number(contractMatch[1])} />;
  else if (route === "/invoices") page = <Invoices />;
  else page = <Contracts />;

  const section = route.startsWith("/invoices") ? "invoices" : "contracts";

  return (
    <div className="shell">
      <header className="topbar">
        <a className="wordmark" href="#/">
          <span className="wordmark-mark" aria-hidden="true" />
          GetPaid
        </a>
        <nav className="topnav" aria-label="Main">
          <a href="#/" aria-current={section === "contracts" ? "page" : undefined}>Contracts</a>
          <a href="#/invoices" aria-current={section === "invoices" ? "page" : undefined}>Invoices</a>
        </nav>
        <div className="topbar-user">
          <span>{session.name}</span>
          <button className="link-button" onClick={logOut}>Log out</button>
        </div>
      </header>
      <main className="page">{page}</main>
    </div>
  );
}
