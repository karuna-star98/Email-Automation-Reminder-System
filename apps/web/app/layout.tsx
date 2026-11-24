import './globals.css'
export const metadata = { title: 'Email Automation & Reminders', description: 'Schedule, send and monitor email reminders' }
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (<html lang="en"><body>{children}</body></html>)
}
