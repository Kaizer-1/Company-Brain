import { Outlet } from 'react-router-dom';
import { useKeyboardNav } from '../../hooks/useKeyboardNav';
import { TopBar } from './TopBar';

export function Layout() {
  useKeyboardNav();

  return (
    <div className="flex flex-col h-screen bg-bg overflow-hidden">
      <TopBar />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
