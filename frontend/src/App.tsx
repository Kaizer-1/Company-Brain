import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { Ask } from './pages/Ask';
import { Audit } from './pages/Audit';
import { Graph } from './pages/Graph';
import { Ingest } from './pages/Ingest';
import { Landing } from './pages/Landing';
import { Queries } from './pages/Queries';
import { Search } from './pages/Search';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Landing />} />
          <Route path="ask" element={<Ask />} />
          <Route path="ingest" element={<Ingest />} />
          <Route path="graph" element={<Graph />} />
          <Route path="queries" element={<Queries />} />
          <Route path="search" element={<Search />} />
          <Route path="audit" element={<Audit />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
