import { lazy, Suspense } from "react";
import ChatApp from "./chat/ChatApp";
import { ZoomProvider } from "./components/ImageZoom";

const AdminApp = lazy(() => import("./admin/AdminApp"));

// Két oldal, router nélkül: / = chat, /admin = admin felület.
export default function App() {
  const isAdmin = window.location.pathname.startsWith("/admin");
  return (
    <ZoomProvider>
      {isAdmin ? (
        <Suspense fallback={<div className="page-loading">Betöltés…</div>}>
          <AdminApp />
        </Suspense>
      ) : (
        <ChatApp />
      )}
    </ZoomProvider>
  );
}
