import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ActionsPage } from './pages/ActionsPage';
import { AnomaliesPage } from './pages/AnomaliesPage';
import { AwsResourcesPage } from './pages/AwsResourcesPage';
import { DashboardPage } from './pages/DashboardPage';
import { ResourcesPage } from './pages/ResourcesPage';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/resources" element={<ResourcesPage />} />
        <Route path="/aws/resources" element={<AwsResourcesPage />} />
        <Route path="/anomalies" element={<AnomaliesPage />} />
        <Route path="/actions" element={<ActionsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
