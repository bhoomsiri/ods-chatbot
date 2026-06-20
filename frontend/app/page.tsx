import ChatWindow from "@/components/ChatWindow";
import Sidebar from "@/components/Sidebar";

export default function Home() {
  return (
    <main className="flex h-screen w-full overflow-hidden bg-slate-100">
      <Sidebar />
      <ChatWindow />
    </main>
  );
}
