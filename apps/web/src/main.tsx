import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles.css";

import { Shell } from "./components/Shell";
import { OverviewScreen } from "./screens/Overview";
import { RecordingsScreen } from "./screens/Recordings";
import { RecordingScreen } from "./screens/Recording";
import { AskScreen } from "./screens/Ask";
import { ObjectsScreen } from "./screens/Objects";
import { DiaryScreen } from "./screens/Diary";
import { SystemScreen } from "./screens/System";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<OverviewScreen />} />
          <Route path="recordings" element={<RecordingsScreen />} />
          <Route path="recordings/:id" element={<RecordingScreen />} />
          <Route path="ask" element={<AskScreen />} />
          <Route path="objects" element={<ObjectsScreen />} />
          <Route path="diary" element={<DiaryScreen />} />
          <Route path="system" element={<SystemScreen />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
