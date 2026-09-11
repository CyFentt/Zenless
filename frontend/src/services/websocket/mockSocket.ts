import type { SocketStatus, ZenlessEvent, ZenlessEventHandler } from "@/types";
import type { ZenlessSocket } from "./socket";
import type { MockZenlessAPI } from "../mock/mockApi";
import { mockConnections } from "../mock/mockData";

type StatusHandler = (status: SocketStatus) => void;

export class MockZenlessSocket implements ZenlessSocket {
  private status: SocketStatus = "DISCONNECTED";
  private eventHandlers = new Set<ZenlessEventHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private respondedMessages = new Set<string>();
  private mockApi: MockZenlessAPI;
  private started = false;

  constructor(mockApi: MockZenlessAPI) {
    this.mockApi = mockApi;
  }

  connect() {
    if (this.status === "CONNECTING" || this.status === "CONNECTED") return;
    this.setStatus("CONNECTING");
    this.schedule(() => {
      this.setStatus("CONNECTED");
      if (!this.started) {
        this.started = true;
        this.startSimulation();
      }
    }, 600);
  }

  disconnect() {
    this.timers.forEach((timer) => clearTimeout(timer));
    this.timers.clear();
    this.respondedMessages.clear();
    this.started = false;
    this.setStatus("DISCONNECTED");
  }

  on(event: "event" | "status", handler: ZenlessEventHandler | StatusHandler): () => void {
    if (event === "event") {
      this.eventHandlers.add(handler as ZenlessEventHandler);
      return () => this.eventHandlers.delete(handler as ZenlessEventHandler);
    }
    this.statusHandlers.add(handler as StatusHandler);
    return () => this.statusHandlers.delete(handler as StatusHandler);
  }

  getStatus() {
    return this.status;
  }

  emit(event: ZenlessEvent) {
    this.eventHandlers.forEach((h) => h(event));
  }

  private setStatus(s: SocketStatus) {
    this.status = s;
    this.statusHandlers.forEach((h) => h(s));
  }

  private schedule(callback: () => void, delay: number) {
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      callback();
    }, delay);
    this.timers.add(timer);
  }

  private startSimulation() {
    this.schedule(() => {
      this.mockApi.setMockConnection("hunyuan", "READY");
      this.mockApi.setMockAgentStatus("hunyuan", "READY");
      this.emit({ type: "CONNECTION_CHANGED", data: { hunyuan: "READY" } });
      this.emit({ type: "AGENT_STATUS_CHANGED", data: { agent: "hunyuan", status: "READY" } });
    }, 3000);

    this.schedule(() => {
      this.mockApi.setMockConnection("studio", "READY");
      this.mockApi.setMockAgentStatus("studio", "READY");
      this.emit({ type: "CONNECTION_CHANGED", data: { studio: "READY" } });
      this.emit({ type: "STUDIO_STATE_CHANGED", data: { state: "ONLINE" } });
    }, 5000);

    const checkInterval = setInterval(() => {
      const msgs = this.mockApi.getMockMessages();
      const lastUser = [...msgs].reverse().find((m) => m.role === "user");
      if (!lastUser || this.respondedMessages.has(lastUser.id)) return;
      this.respondedMessages.add(lastUser.id);

      const responseId = `msg_${Date.now()}`;
      const jobId = lastUser.jobId ?? "mock_job";
      this.emit({
        type: "CHAT_STREAM_STARTED",
        data: { jobId, messageId: responseId },
      });

      const fullText =
        "Analyzing request. I will review the relevant scripts and propose changes for your approval.";
      const words = fullText.split(" ");
      let idx = 0;
      const streamTimer = setInterval(() => {
        if (idx >= words.length) {
          clearInterval(streamTimer);
          this.timers.delete(streamTimer);
          this.emit({ type: "CHAT_STREAM_FINISHED", data: { jobId, messageId: responseId } });
          return;
        }
        const delta = (idx === 0 ? "" : " ") + words[idx];
        this.emit({ type: "CHAT_STREAM_DELTA", data: { jobId, messageId: responseId, delta } });
        idx++;
      }, 80);
      this.timers.add(streamTimer);
    }, 1000);
    this.timers.add(checkInterval);

    const testInterval = setInterval(() => {
      const ts = this.mockApi.getMockTestState();
      if (ts.status !== "RUNNING") return;
      const logId = `log_${Date.now()}`;
      const levels = ["SRV", "CLI", "ZEN", "WARN"] as const;
      const level = levels[Math.floor(Math.random() * levels.length)];
      const messages = [
        "Physics step completed",
        "Player character spawned",
        "Remote event fired",
        "Memory: 45MB",
        "Frame: 60fps",
        "Replication update",
      ];
      const msg = messages[Math.floor(Math.random() * messages.length)];
      const log = { id: logId, timestamp: Date.now(), level, message: msg };
      this.mockApi.addMockLog(log);
      this.emit({ type: "TEST_LOG", data: { jobId: this.mockApi.getMockCurrentJobId(), log } });
    }, 2000);
    this.timers.add(testInterval);
  }
}

export { mockConnections };
