/**
 * ============================================================================
 * AI TUTOR INTERFACE - LearnAI Platform
 * ============================================================================
 * 
 * Chat interface for students to interact with the AI tutor.
 * Supports text, equations, and diagram uploads.
 * 
 * FEATURES:
 * - Real-time chat with AI
 * - Equation rendering support
 * - Image upload for diagram analysis
 * - Conversation history
 * - Context-aware responses
 * 
 * ============================================================================
 */

import { useState, useRef, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { useAuth, useApp } from '@/contexts';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent } from '@/components/ui/card';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Bot,
  Send,
  Image as ImageIcon,
  MoreVertical,
  Plus,
  Sparkles,
  Loader2,
  ChevronLeft,
  MessageSquare,
} from 'lucide-react';
import type { ChatMessage, Conversation } from '@/types';

// =============================================================================
// MOCK CONVERSATIONS
// =============================================================================

const MOCK_CONVERSATIONS: Conversation[] = [
  {
    id: 'conv-1',
    userId: 'student-1',
    title: 'Force Components Help',
    messages: [
      {
        id: 'msg-1',
        conversationId: 'conv-1',
        sender: 'user',
        type: 'text',
        content: 'I\'m struggling with calculating force components. Can you explain?',
        timestamp: new Date(Date.now() - 86400000),
      },
      {
        id: 'msg-2',
        conversationId: 'conv-1',
        sender: 'ai',
        type: 'text',
        content: 'I\'d be happy to help! When a force acts at an angle, we break it into horizontal (x) and vertical (y) components using trigonometry.\n\nFor a force F at angle θ:\n• Horizontal: Fₓ = F × cos(θ)\n• Vertical: Fᵧ = F × sin(θ)\n\nWould you like to work through an example problem?',
        timestamp: new Date(Date.now() - 86350000),
      },
    ],
    createdAt: new Date(Date.now() - 86400000),
    updatedAt: new Date(Date.now() - 86350000),
    contextCourseId: 'course-1',
  },
  {
    id: 'conv-2',
    userId: 'student-1',
    title: 'Thermodynamics Question',
    messages: [
      {
        id: 'msg-3',
        conversationId: 'conv-2',
        sender: 'user',
        type: 'text',
        content: 'What is the First Law of Thermodynamics?',
        timestamp: new Date(Date.now() - 172800000),
      },
      {
        id: 'msg-4',
        conversationId: 'conv-2',
        sender: 'ai',
        type: 'text',
        content: 'The First Law of Thermodynamics states that energy cannot be created or destroyed, only transferred or converted from one form to another.\n\nMathematically: ΔU = Q - W\n\nWhere:\n• ΔU = change in internal energy\n• Q = heat added to the system\n• W = work done by the system',
        timestamp: new Date(Date.now() - 172750000),
      },
    ],
    createdAt: new Date(Date.now() - 172800000),
    updatedAt: new Date(Date.now() - 172750000),
    contextCourseId: 'course-2',
  },
];

// =============================================================================
// SUGGESTED QUESTIONS
// =============================================================================

const SUGGESTED_QUESTIONS = [
  'Explain force vectors',
  'How do I solve equilibrium problems?',
  'What is Hooke\'s Law?',
  'Help with stress-strain calculations',
  'Explain the Carnot cycle',
];

// =============================================================================
// MESSAGE BUBBLE COMPONENT
// =============================================================================

interface MessageBubbleProps {
  message: ChatMessage;
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.sender === 'user';

  return (
    <div
      className={cn(
        'flex gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      <Avatar className={cn('w-8 h-8', isUser ? 'bg-indigo-500' : 'bg-gradient-to-br from-teal-500 to-cyan-500')}>
        {isUser ? (
          <AvatarFallback className="bg-indigo-500 text-white text-xs">You</AvatarFallback>
        ) : (
          <Bot className="w-4 h-4 text-white" />
        )}
      </Avatar>

      <div className={cn('max-w-[70%]', isUser ? 'items-end' : 'items-start')}>
        <Card
          className={cn(
            'border-0 shadow-sm',
            isUser
              ? 'bg-indigo-600 text-white'
              : 'bg-white'
          )}
        >
          <CardContent className="p-3">
            {/* Equation rendering would go here */}
            {message.type === 'equation' && message.latexContent && (
              <div className="mb-2 p-2 bg-slate-100 rounded font-mono text-sm">
                {message.latexContent}
              </div>
            )}
            
            {/* Image rendering */}
            {message.imageUrl && (
              <img
                src={message.imageUrl}
                alt="Uploaded diagram"
                className="max-w-full rounded-lg mb-2"
              />
            )}
            
            <p className={cn('text-sm whitespace-pre-wrap', isUser ? 'text-white' : 'text-slate-700')}>
              {message.content}
            </p>
          </CardContent>
        </Card>
        <span className="text-xs text-slate-400 mt-1">
          {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
    </div>
  );
}

// =============================================================================
// TYPING INDICATOR
// =============================================================================

function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <Avatar className="w-8 h-8 bg-gradient-to-br from-teal-500 to-cyan-500">
        <Bot className="w-4 h-4 text-white" />
      </Avatar>
      <Card className="border-0 shadow-sm bg-white">
        <CardContent className="p-3">
          <div className="flex gap-1">
            <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

interface AITutorProps {
  onViewChange: (view: string) => void;
}

export function AITutor({ onViewChange }: AITutorProps) {
  const { user } = useAuth();
  const { sendMessageToAI, conversations, createConversation } = useApp();
  
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [inputMessage, setInputMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Derive active conversation from context so it always has fresh messages
  const activeConversation = conversations.find(c => c.id === activeConversationId) ?? null;

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, isTyping]);

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || !activeConversationId) return;

    const message = inputMessage.trim();
    setInputMessage('');
    setIsTyping(true);

    try {
      await sendMessageToAI(activeConversationId, message);
    } catch (err) {
      console.error('AI tutor error:', err);
    } finally {
      setIsTyping(false);
    }
  };

  const handleNewConversation = () => {
    const newConv = createConversation('New Conversation');
    setActiveConversationId(newConv.id);
  };

  const handleImageUpload = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && activeConversationId) {
      const imageUrl = URL.createObjectURL(file);
      
      // Send a message with the image description to the AI
      const messageWithImage = `[Image uploaded] Can you analyze this diagram? ${imageUrl}`;
      setIsTyping(true);
      sendMessageToAI(activeConversationId, messageWithImage)
        .catch(console.error)
        .finally(() => setIsTyping(false));
    }
  };

  return (
    <div className="h-full flex animate-in fade-in duration-500">
      {/* Sidebar - Conversation List */}
      {showSidebar && (
        <div className="w-72 border-r bg-slate-50 flex flex-col">
          <div className="p-4 border-b bg-white">
            <div className="flex items-center justify-between mb-4">
              <Button variant="ghost" size="icon" onClick={() => onViewChange('dashboard')}>
                <ChevronLeft className="w-5 h-5" />
              </Button>
              <h2 className="font-semibold">AI Tutor</h2>
            </div>
            <Button 
              className="w-full gap-2 bg-indigo-600 hover:bg-indigo-700"
              onClick={handleNewConversation}
            >
              <Plus className="w-4 h-4" />
              New Chat
            </Button>
          </div>

          <ScrollArea className="flex-1">
            <div className="p-2 space-y-1">
              {conversations.map((conv) => (
                <button
                  key={conv.id}
                  onClick={() => setActiveConversationId(conv.id)}
                  className={cn(
                    'w-full text-left p-3 rounded-xl transition-all',
                    activeConversation?.id === conv.id
                  )}
                >
                  <div className="flex items-center gap-2">
                    <MessageSquare className="w-4 h-4 flex-shrink-0" />
                    <span className="font-medium text-sm truncate">{conv.title}</span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1 truncate">
                    {conv.messages[conv.messages.length - 1]?.content.slice(0, 50)}...
                  </p>
                </button>
              ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col bg-white">
        {activeConversation ? (
          <>
            {/* Chat Header */}
            <div className="flex items-center justify-between p-4 border-b">
              <div className="flex items-center gap-3">
                {!showSidebar && (
                  <Button variant="ghost" size="icon" onClick={() => setShowSidebar(true)}>
                    <MessageSquare className="w-5 h-5" />
                  </Button>
                )}
                <div className="w-10 h-10 bg-gradient-to-br from-teal-500 to-cyan-500 rounded-xl flex items-center justify-center">
                  <Bot className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h3 className="font-semibold">LearnAI Tutor</h3>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 bg-green-500 rounded-full" />
                    <span className="text-xs text-slate-500">Online</span>
                  </div>
                </div>
              </div>
              <Button variant="ghost" size="icon">
                <MoreVertical className="w-5 h-5" />
              </Button>
            </div>

            {/* Messages */}
            <ScrollArea className="flex-1 p-4">
              <div className="space-y-4 max-w-3xl mx-auto">
                {/* Welcome message if no messages */}
                {activeConversation.messages.length === 0 && (
                  <div className="text-center py-8">
                    <div className="w-20 h-20 bg-gradient-to-br from-indigo-100 to-teal-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <Sparkles className="w-10 h-10 text-indigo-500" />
                    </div>
                    <h3 className="text-xl font-semibold text-slate-800 mb-2">
                      How can I help you today?
                    </h3>
                    <p className="text-slate-500 mb-6">
                      I can help you understand concepts, solve equations, or analyze diagrams.
                    </p>
                    
                    {/* Suggested Questions */}
                    <div className="flex flex-wrap justify-center gap-2">
                      {SUGGESTED_QUESTIONS.map((q, i) => (
                        <button
                          key={i}
                          onClick={() => setInputMessage(q)}
                          className="px-4 py-2 bg-slate-100 hover:bg-indigo-100 text-slate-700 hover:text-indigo-700 rounded-full text-sm transition-colors"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Message bubbles */}
                {activeConversation.messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
                
                {isTyping && <TypingIndicator />}
                <div ref={messagesEndRef} />
              </div>
            </ScrollArea>

            {/* Input Area */}
            <div className="p-4 border-t bg-slate-50">
              <div className="max-w-3xl mx-auto">
                <div className="flex items-end gap-2">
                  <div className="flex-1 relative">
                    <Textarea
                      value={inputMessage}
                      onChange={(e) => setInputMessage(e.target.value)}
                      placeholder="Ask a question, paste an equation, or upload a diagram..."
                      className="min-h-[80px] pr-12 resize-none"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleSendMessage();
                        }
                      }}
                    />
                    <div className="absolute bottom-3 right-3 flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-slate-400 hover:text-indigo-600"
                        onClick={handleImageUpload}
                      >
                        <ImageIcon className="w-4 h-4" />
                      </Button>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={handleFileChange}
                      />
                    </div>
                  </div>
                  <Button
                    className="h-10 px-4 bg-indigo-600 hover:bg-indigo-700"
                    onClick={handleSendMessage}
                    disabled={!inputMessage.trim() || isTyping}
                  >
                    {isTyping ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Send className="w-4 h-4" />
                    )}
                  </Button>
                </div>
                <p className="text-xs text-slate-400 mt-2 text-center">
                  AI Tutor can make mistakes. Verify important information with your professor.
                </p>
              </div>
            </div>
          </>
        ) : (
          /* Empty State */
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center space-y-4">
              <div className="w-24 h-24 bg-gradient-to-br from-indigo-100 to-teal-100 rounded-full flex items-center justify-center mx-auto">
                <Bot className="w-12 h-12 text-indigo-500" />
              </div>
              <div>
                <h3 className="text-xl font-semibold text-slate-700">Start a New Conversation</h3>
                <p className="text-slate-500 max-w-md mt-2">
                  Click "New Chat" to start learning with your AI tutor.
                </p>
              </div>
              <Button 
                className="gap-2 bg-indigo-600 hover:bg-indigo-700"
                onClick={handleNewConversation}
              >
                <Plus className="w-4 h-4" />
                New Chat
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
