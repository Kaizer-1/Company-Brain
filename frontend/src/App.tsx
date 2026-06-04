import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { Audit } from './pages/Audit';
import { Graph } from './pages/Graph';
import { Landing } from './pages/Landing';
import { Queries } from './pages/Queries';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Landing />} />
          <Route path="graph" element={<Graph />} />
          <Route path="queries" element={<Queries />} />
          <Route path="audit" element={<Audit />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
