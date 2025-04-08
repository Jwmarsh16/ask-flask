import './App.css'
import ChatBot from './components/ChatBot'

function App() {
  return (
    <div className="app-container">
      <h1 className="text-2xl font-bold mb-4 text-white">Ask Flask</h1>
      <ChatBot />
    </div>
  )
}

export default App
