import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import AppShell from "./components/AppShell";
import Home from "./pages/Home";
import SubmitDocument from "./pages/SubmitDocument";
import AskQuestion from "./pages/AskQuestion";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Home />} />
          <Route path="/ask" element={<AskQuestion />} />
          <Route path="/submit" element={<SubmitDocument />} />
          <Route
            path="*"
            element={
              <section className="empty-panel">
                <h1>Page not found</h1>
                <Link className="btn btn-primary" to="/">
                  Back to overview
                </Link>
              </section>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
