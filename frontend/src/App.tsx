
function App() {
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 transform transition-all hover:scale-105 duration-300">
        <h1 className="text-3xl font-bold text-center bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-600 mb-4">
          ContiCheck
        </h1>
        <p className="text-slate-600 text-center mb-6">
          Phase 0: Frontend Scaffolding initialized successfully.
        </p>
        <div className="flex justify-center">
          <button className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg transition-colors shadow-md shadow-indigo-200">
             Get Started
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
