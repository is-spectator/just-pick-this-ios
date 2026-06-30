import Foundation
import CoreLocation
import Observation
import Security

enum RecommendationDecision: Sendable {
    case none
    case top1(TopPick)
    case ask(HelpRequest)

    var isEmpty: Bool {
        if case .none = self {
            return true
        }
        return false
    }
}

struct RecommendationResult: Sendable {
    let sessionId: UUID?
    let questionId: UUID?
    let history: [QuestionHistory]
    let decision: RecommendationDecision
    let serviceNotice: ServiceNotice?
}

struct ServiceNotice: Equatable, Sendable {
    let title: String
    let detail: String

    var isRetryable: Bool {
        title == "皮皮" && detail.contains("重试")
    }
}

struct PublishHelpResult: Sendable {
    let request: HelpRequest
    let didPublish: Bool
    let notice: ServiceNotice?
}

struct SubmitHelpAnswerResult: Sendable {
    let request: HelpRequest?
    let didSubmit: Bool
    let notice: ServiceNotice?
}

struct CompleteQuestionResult: Sendable {
    let didComplete: Bool
    let history: [QuestionHistory]
    let notice: ServiceNotice?
}

struct MyHelpRequestsResult: Sendable {
    let requests: [HelpRequest]
    let notice: ServiceNotice?
}

struct QuestionHistory: Identifiable, Hashable, Codable, Sendable {
    let id: UUID
    let query: String
    let status: String
    let helpRequestId: UUID?
    let topPick: TopPick?
    let createdAt: String?

    var statusLabel: String {
        switch status {
        case "completed":
            "已完成"
        case "top1":
            "已给选择"
        case "waiting_for_human":
            "等人来一句"
        case "answer_received":
            "已收到一句"
        case "draft":
            "待发布"
        case "closed":
            "已关闭"
        default:
            "处理中"
        }
    }
}

enum HistoryDestination {
    case result
    case ask
}

struct TopPick: Hashable, Codable, Sendable {
    let cardId: UUID?
    let query: String
    let preface: String
    let title: String
    let subtitle: String
    let reason: String
    let bullets: [String]
    let warning: String
    let followups: [String]
    let referenceImage: ReferenceImage?
}

struct ReferenceImage: Hashable, Codable, Sendable {
    let url: String
    let sourceURL: String?
    let sourceDomain: String?
    let caption: String?
    let isAiGenerated: Bool
}

enum HelpRequestStatus: String, Codable, Hashable, Sendable {
    case draft
    case published
    case answered
    case completed
    case closed

    var label: String {
        switch self {
        case .draft:
            "待发布"
        case .published:
            "已发布"
        case .answered:
            "已收到一句"
        case .completed:
            "已采纳"
        case .closed:
            "已关闭"
        }
    }
}

struct HumanAnswer: Identifiable, Hashable, Sendable {
    let id: UUID
    let text: String
    let nickname: String
    let timeLabel: String

    init(id: UUID = UUID(), text: String, nickname: String, timeLabel: String) {
        self.id = id
        self.text = text
        self.nickname = nickname
        self.timeLabel = timeLabel
    }
}

struct HelpRequest: Identifiable, Hashable, Sendable {
    let id: UUID
    var title: String
    var context: String
    var rewardLabel: String
    var answerCount: Int
    var status: HelpRequestStatus
    var answers: [HumanAnswer]
    var finalPick: TopPick?
    var createdAt: String?

    init(
        id: UUID = UUID(),
        title: String,
        context: String,
        rewardLabel: String = "+10",
        answerCount: Int = 0,
        status: HelpRequestStatus = .draft,
        answers: [HumanAnswer] = [],
        finalPick: TopPick? = nil,
        createdAt: String? = nil
    ) {
        self.id = id
        self.title = title
        self.context = context
        self.rewardLabel = rewardLabel
        self.answerCount = answerCount
        self.status = status
        self.answers = answers
        self.finalPick = finalPick
        self.createdAt = createdAt
    }
}

enum SubmitState: Equatable {
    case idle
    case loading
}

struct DecisionLocationContext: Equatable, Codable, Sendable {
    let label: String
    let city: String?
    let area: String?
    let latitude: Double?
    let longitude: Double?
    let source: String

    var displayLabel: String {
        label.isEmpty ? "选择地点" : label
    }

    var detailLabel: String {
        switch source {
        case "current":
            "当前定位"
        case "manual":
            "手动地点"
        default:
            "决策地点"
        }
    }

    static func manual(_ rawValue: String) -> DecisionLocationContext? {
        let label = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !label.isEmpty else { return nil }

        return context(label: label, source: "manual")
    }

    static func inferred(from message: String) -> DecisionLocationContext? {
        let normalized = message
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return nil }

        for marker in ["我到了", "我到", "我在", "现在在", "目前在"] {
            if let label = locationLabel(after: marker, in: normalized) {
                return context(label: label, source: "message")
            }
        }

        let knownLocations = [
            "上海互联网宝地",
            "北京三里屯",
            "北京市朝阳区",
            "朝阳区",
            "望京 SOHO",
            "望京SOHO",
            "南锣鼓巷",
            "大同古城",
            "五道口"
        ]
        if let label = knownLocations.first(where: { normalized.localizedCaseInsensitiveContains($0) }) {
            return context(label: label, source: "message")
        }

        return nil
    }

    private static func context(label: String, source: String) -> DecisionLocationContext? {
        let label = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !label.isEmpty else { return nil }

        let cityCandidates = ["北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "南京", "苏州", "武汉", "西安", "长沙", "厦门", "大同"]
        let city = cityCandidates.first { label.localizedCaseInsensitiveContains($0) }
        let area = city == label ? nil : label
        return DecisionLocationContext(
            label: label,
            city: city,
            area: area,
            latitude: nil,
            longitude: nil,
            source: source
        )
    }

    private static func locationLabel(after marker: String, in text: String) -> String? {
        guard let markerRange = text.range(of: marker, options: [.caseInsensitive]) else { return nil }
        let remainder = text[markerRange.upperBound...]
        let stopCharacters = CharacterSet(charactersIn: "，,。.!！?？；;、\n")
        let firstClause = String(remainder.prefix { scalar in
            String(scalar).rangeOfCharacter(from: stopCharacters) == nil
        })
        let stopWords = ["想", "要", "帮", "给", "找", "吃", "点", "喝", "逛", "买"]
        var label = firstClause.trimmingCharacters(in: .whitespacesAndNewlines)
        for stopWord in stopWords {
            if let range = label.range(of: stopWord) {
                label = String(label[..<range.lowerBound])
            }
        }
        label = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard label.count >= 2 else { return nil }
        return label
    }
}

enum CardFeedbackAction: String, Sendable {
    case reject
    case change
    case askHuman = "ask-human"

    var endpointPath: String {
        rawValue
    }
}

protocol RecommendationService: Sendable {
    func submit(query: String, sessionId: UUID?, locationContext: DecisionLocationContext?) async -> RecommendationResult
    func publish(_ request: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> PublishHelpResult
    func refresh(_ request: HelpRequest) async -> HelpRequest
    func fetchHelpRequest(id: UUID) async -> HelpRequest?
    func myHelpRequests(limit: Int) async -> MyHelpRequestsResult
    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest]
    func answer(_ text: String, for request: HelpRequest) async -> SubmitHelpAnswerResult
    func skip(_ request: HelpRequest, reason: String) async -> Bool
    func acceptCard(id: UUID?) async -> Bool
    func sendCardFeedback(id: UUID?, action: CardFeedbackAction, reason: String) async -> Bool
    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> CompleteQuestionResult
}

enum AppAPIEnvironment {
    static let baseURL: URL = {
        if let configured = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String,
           let url = URL(string: configured),
           !configured.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return url
        }
        return URL(string: "http://67.230.169.161:8788")!
    }()
}

struct BackendRecommendationService: RecommendationService {
    private let baseURL = AppAPIEnvironment.baseURL
    private let deviceUid = DeviceIdentity.uid

    func submit(query: String, sessionId: UUID?, locationContext: DecisionLocationContext?) async -> RecommendationResult {
        do {
            let payload = try await submitChatTurn(query: query, conversationId: sessionId, locationContext: locationContext)
            return payload.result(for: query)
        } catch {
            if shouldRetryWithFreshConversation(after: error, sessionId: sessionId) {
                do {
                    let payload = try await submitChatTurn(query: query, conversationId: nil, locationContext: locationContext)
                    return payload.result(for: query)
                } catch {
                    debugLog("submit retry failed")
                }
            }

            debugLog("submit failed")
            return RecommendationResult(
                sessionId: sessionId,
                questionId: nil,
                history: [],
                decision: .none,
                serviceNotice: MockData.backendUnavailableNotice(error: error)
            )
        }
    }

    private func submitChatTurn(
        query: String,
        conversationId: UUID?,
        locationContext: DecisionLocationContext?
    ) async throws -> V1ChatTurnResponse {
        return try await perform(makeRequest(
            path: "/v1/chat/turn",
            method: "POST",
            body: V1ChatTurnRequest(
                message: query,
                conversationId: conversationId?.uuidString,
                deviceId: deviceUid,
                clientContext: V1ClientContext(
                    source: "ios",
                    location: locationContext.flatMap(V1ClientLocation.init(context:)),
                    decisionLocation: locationContext.map(V1DecisionLocationContext.init(context:))
                ),
                metadata: [:]
            )
        ))
    }

    func publish(_ helpRequest: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> PublishHelpResult {
        do {
            let response: V1ChatTurnResponse = try await perform(makeRequest(
                path: "/v1/chat/turn",
                method: "POST",
                body: V1ChatTurnRequest(
                    message: "发出去",
                    conversationId: sessionId?.uuidString,
                    deviceId: deviceUid,
                    clientContext: V1ClientContext(source: "ios", location: nil, decisionLocation: nil),
                    metadata: ["help_card_id": helpRequest.id.uuidString]
                )
            ))
            let published = response.helpCards?.first?.model(fallbackTitle: helpRequest.title) ?? publishedFallback(helpRequest)
            return PublishHelpResult(request: published, didPublish: true, notice: nil)
        } catch {
            return PublishHelpResult(
                request: helpRequest,
                didPublish: false,
                notice: MockData.publishUnavailableNotice(error: error)
            )
        }
    }

    func refresh(_ helpRequest: HelpRequest) async -> HelpRequest {
        guard helpRequest.status == .published else { return helpRequest }

        do {
            var components = URLComponents(url: endpoint("/v1/light-events"), resolvingAgainstBaseURL: false)!
            components.queryItems = [
                URLQueryItem(name: "device_id", value: deviceUid),
                URLQueryItem(name: "limit", value: "10")
            ]
            guard let url = components.url else { return helpRequest }
            let response: V1LightEventsResponse = try await perform(URLRequest(url: url))
            guard response.items.contains(where: { $0.helpCardId == helpRequest.id.uuidString }) else {
                return helpRequest
            }

            if let refreshed = await fetchHelpRequest(id: helpRequest.id) {
                return refreshed
            }

            var refreshed = helpRequest
            refreshed.status = .answered
            refreshed.answers.append(HumanAnswer(text: "皮皮已经根据来一句汇总出结果。", nickname: "皮皮", timeLabel: "刚刚"))
            return refreshed
        } catch {
            return helpRequest
        }
    }

    func fetchHelpRequest(id: UUID) async -> HelpRequest? {
        do {
            let response: V1HelpCardDetailEnvelope = try await perform(URLRequest(url: endpoint("/v1/help-cards/\(id.uuidString)")))
            return response.summary.model(fallbackTitle: "求一个")
        } catch {
            return nil
        }
    }

    func myHelpRequests(limit: Int) async -> MyHelpRequestsResult {
        do {
            var components = URLComponents(url: endpoint("/v1/help-cards/mine"), resolvingAgainstBaseURL: false)!
            components.queryItems = [
                URLQueryItem(name: "device_id", value: deviceUid),
                URLQueryItem(name: "limit", value: "\(max(1, min(limit, 100)))")
            ]

            guard let url = components.url else {
                return MyHelpRequestsResult(requests: [], notice: MockData.myHelpUnavailableNotice())
            }
            let response: V1HelpFeedResponse = try await perform(URLRequest(url: url))
            return MyHelpRequestsResult(
                requests: response.items.map { $0.model(fallbackTitle: "求一个") },
                notice: nil
            )
        } catch {
            return MyHelpRequestsResult(requests: [], notice: MockData.myHelpUnavailableNotice())
        }
    }

    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest] {
        do {
            var components = URLComponents(url: endpoint("/v1/help-feed"), resolvingAgainstBaseURL: false)!
            let queryItems = [
                URLQueryItem(name: "device_id", value: deviceUid),
                URLQueryItem(name: "limit", value: "10")
            ]
            components.queryItems = queryItems

            guard let url = components.url else { return [] }
            let response: V1HelpFeedResponse = try await perform(URLRequest(url: url))
            return response.items.map { $0.model(fallbackTitle: "求一个") }
        } catch {
            return []
        }
    }

    func answer(_ text: String, for helpRequest: HelpRequest) async -> SubmitHelpAnswerResult {
        do {
            let response: V1HelpCardOneLinerResponse = try await perform(makeRequest(
                path: "/v1/help-cards/\(helpRequest.id.uuidString)/one-liner",
                method: "POST",
                body: V1HelpCardOneLinerRequest(text: text, deviceId: deviceUid)
            ))
            var updated = helpRequest
            updated.answers.append(HumanAnswer(id: response.answerId ?? UUID(), text: text, nickname: "路过的人", timeLabel: "刚刚"))
            updated.rewardLabel = response.reward?.label ?? updated.rewardLabel
            updated.answerCount += 1
            updated.status = response.isFinalReady ? .answered : .published
            return SubmitHelpAnswerResult(request: updated, didSubmit: true, notice: nil)
        } catch {
            return SubmitHelpAnswerResult(
                request: helpRequest,
                didSubmit: false,
                notice: MockData.answerUnavailableNotice(error: error)
            )
        }
    }

    func skip(_ helpRequest: HelpRequest, reason: String) async -> Bool {
        do {
            let _: V1HelpCardSkipResponse = try await perform(makeRequest(
                path: "/v1/help-cards/\(helpRequest.id.uuidString)/skip",
                method: "POST",
                body: V1HelpCardSkipRequest(
                    deviceId: deviceUid,
                    reason: reason,
                    metadata: ["source": "ios", "surface": "answer_deck"]
                )
            ))
            return true
        } catch {
            return false
        }
    }

    func acceptCard(id: UUID?) async -> Bool {
        guard let id else { return false }

        do {
            let response: V1CardAcceptResponse = try await perform(makeRequest(
                path: "/v1/cards/\(id.uuidString)/accept",
                method: "POST",
                body: V1CardAcceptRequest(metadata: ["source": "ios"])
            ))
            return response.accepted
        } catch {
            return false
        }
    }

    func sendCardFeedback(id: UUID?, action: CardFeedbackAction, reason: String) async -> Bool {
        guard let id else { return false }

        do {
            let _: V1CardFeedbackResponse = try await perform(makeRequest(
                path: "/v1/cards/\(id.uuidString)/\(action.endpointPath)",
                method: "POST",
                body: V1CardFeedbackRequest(
                    deviceId: deviceUid,
                    reason: reason,
                    tags: [reason],
                    metadata: ["source": "ios", "surface": "chat_card"]
                )
            ))
            return true
        } catch {
            return false
        }
    }

    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> CompleteQuestionResult {
        guard let helpRequestId else {
            return CompleteQuestionResult(
                didComplete: false,
                history: [],
                notice: MockData.acceptUnavailableNotice()
            )
        }

        do {
            let response: V1HelpCardFinalAcceptResponse = try await perform(makeRequest(
                path: "/v1/help-cards/\(helpRequestId.uuidString)/accept-final",
                method: "POST",
                body: V1HelpCardFinalAcceptRequest(
                    deviceId: deviceUid,
                    reason: source == "human_answer" ? "采纳来一句最终结果" : "采纳皮皮结果",
                    metadata: [
                        "source": source,
                        "surface": "ios",
                        "conversation_id": sessionId?.uuidString ?? "",
                        "question_id": questionId?.uuidString ?? ""
                    ].compactMapValues { $0.isEmpty ? nil : $0 }
                )
            ))
            guard response.accepted else {
                return CompleteQuestionResult(
                    didComplete: false,
                    history: [],
                    notice: MockData.acceptUnavailableNotice()
                )
            }
            return CompleteQuestionResult(didComplete: true, history: [], notice: nil)
        } catch {
            return CompleteQuestionResult(
                didComplete: false,
                history: [],
                notice: MockData.acceptUnavailableNotice()
            )
        }
    }

    private func makeRequest<Body: Encodable>(path: String, method: String, body: Body) throws -> URLRequest {
        var request = URLRequest(url: endpoint(path))
        request.httpMethod = method
        request.timeoutInterval = 18
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return request
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        var request = authorized(request)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200..<300).contains(httpResponse.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            if status == 401, await AuthAPIService().refreshIfPossible() {
                request = authorized(request)
                let (retryData, retryResponse) = try await URLSession.shared.data(for: request)
                if let retryHTTP = retryResponse as? HTTPURLResponse,
                   (200..<300).contains(retryHTTP.statusCode) {
                    return try JSONDecoder().decode(Response.self, from: retryData)
                }
            }
            let body = String(data: data, encoding: .utf8) ?? ""
            debugLog("HTTP \(status)")
            throw BackendServiceError.httpStatus(status, body)
        }

        do {
            return try JSONDecoder().decode(Response.self, from: data)
        } catch {
            let body = String(data: data, encoding: .utf8) ?? ""
            debugLog("decode failed")
            throw BackendServiceError.decoding(String(describing: error), body)
        }
    }

    private func debugLog(_ message: String) {
        #if DEBUG
        NSLog("BackendRecommendationService: %@", message)
        #endif
    }

    private func publishedFallback(_ helpRequest: HelpRequest) -> HelpRequest {
        var fallback = helpRequest
        fallback.status = .published
        return fallback
    }

    private func shouldRetryWithFreshConversation(after error: Error, sessionId: UUID?) -> Bool {
        guard sessionId != nil, let backendError = error as? BackendServiceError else { return false }

        switch backendError {
        case let .httpStatus(status, _):
            return status == 404 || status == 409 || status >= 500
        case .decoding:
            return false
        }
    }

    private func authorized(_ request: URLRequest) -> URLRequest {
        var request = request
        if let accessToken = AuthTokenStore.accessToken, !accessToken.isEmpty {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }
}

private enum BackendServiceError: LocalizedError {
    case httpStatus(Int, String)
    case decoding(String, String)

    var errorDescription: String? {
        switch self {
        case let .httpStatus(status, body):
            "HTTP \(status): \(body.prefix(160))"
        case let .decoding(message, body):
            "JSON decode failed: \(message). Body: \(body.prefix(160))"
        }
    }
}

struct AuthenticatedAccount: Equatable {
    let email: String?
    let displayName: String
}

struct AuthAPIService: Sendable {
    private let baseURL = AppAPIEnvironment.baseURL

    func requestCode(email: String) async throws {
        var request = URLRequest(url: endpoint("/v1/auth/request-code"))
        request.httpMethod = "POST"
        request.timeoutInterval = 18
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(V1AuthRequestCodeRequest(
            email: email,
            deviceId: DeviceIdentity.uid,
            platform: "ios",
            appVersion: "0.1.0"
        ))
        let _: V1AuthRequestCodeResponse = try await perform(request)
    }

    func verify(email: String, code: String) async throws -> AuthenticatedAccount {
        var request = URLRequest(url: endpoint("/v1/auth/verify-code"))
        request.httpMethod = "POST"
        request.timeoutInterval = 18
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(V1AuthVerifyCodeRequest(
            email: email,
            code: code,
            deviceId: DeviceIdentity.uid,
            platform: "ios",
            appVersion: "0.1.0"
        ))
        let response: V1AuthVerifyCodeResponse = try await perform(request)
        AuthTokenStore.accessToken = response.tokens.accessToken
        AuthTokenStore.refreshToken = response.tokens.refreshToken
        AuthTokenStore.email = response.user.email
        AuthTokenStore.displayName = response.user.displayName
        return AuthenticatedAccount(email: response.user.email, displayName: response.user.displayName)
    }

    func updateDisplayName(_ displayName: String) async throws -> AuthenticatedAccount {
        var request = URLRequest(url: endpoint("/v1/auth/me"))
        request.httpMethod = "PATCH"
        request.timeoutInterval = 12
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request = authorized(request)
        request.httpBody = try JSONEncoder().encode(V1AuthUpdateMeRequest(displayName: displayName))
        let response: V1AuthMeResponse = try await perform(request)
        AuthTokenStore.email = response.user.email
        AuthTokenStore.displayName = response.user.displayName
        return AuthenticatedAccount(email: response.user.email, displayName: response.user.displayName)
    }

    func refreshIfPossible() async -> Bool {
        guard let refreshToken = AuthTokenStore.refreshToken, !refreshToken.isEmpty else { return false }
        do {
            var request = URLRequest(url: endpoint("/v1/auth/refresh"))
            request.httpMethod = "POST"
            request.timeoutInterval = 12
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(V1AuthRefreshRequest(refreshToken: refreshToken))
            let response: V1AuthRefreshResponse = try await perform(request)
            AuthTokenStore.accessToken = response.tokens.accessToken
            AuthTokenStore.refreshToken = response.tokens.refreshToken
            return true
        } catch {
            AuthTokenStore.clear()
            return false
        }
    }

    func logout() async {
        guard let refreshToken = AuthTokenStore.refreshToken else {
            AuthTokenStore.clear()
            return
        }
        do {
            var request = URLRequest(url: endpoint("/v1/auth/logout"))
            request.httpMethod = "POST"
            request.timeoutInterval = 12
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(V1AuthRefreshRequest(refreshToken: refreshToken))
            let _: V1AuthLogoutResponse = try await perform(request)
        } catch {
            // Logout is best-effort on the client; local credentials must still go away.
        }
        AuthTokenStore.clear()
    }

    func deleteAccount() async throws {
        guard AuthTokenStore.accessToken?.isEmpty == false else {
            AuthTokenStore.clear()
            return
        }

        var request = URLRequest(url: endpoint("/v1/auth/me"))
        request.httpMethod = "DELETE"
        request.timeoutInterval = 12
        request = authorized(request)
        let _: V1AuthDeleteMeResponse = try await perform(request)
        AuthTokenStore.clear()
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            let body = String(data: data, encoding: .utf8) ?? ""
            throw BackendServiceError.httpStatus(status, body)
        }
        return try JSONDecoder().decode(Response.self, from: data)
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }

    private func authorized(_ request: URLRequest) -> URLRequest {
        var request = request
        if let accessToken = AuthTokenStore.accessToken, !accessToken.isEmpty {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }
}

struct UserLightEvent: Identifiable, Equatable, Sendable {
    let id: String
    let kind: String?
    let title: String
    let body: String
    let cardId: UUID?
    let helpCardId: UUID?
    let createdAt: String?

    var destinationHint: String {
        if helpCardId != nil {
            return "打开求助详情"
        }
        if cardId != nil {
            return "打开相关推荐"
        }
        if kind?.contains("reward") == true {
            return "查看奖励明细"
        }
        return "查看相关内容"
    }
}

struct UserDashboardSnapshot: Equatable, Sendable {
    let pendingReward: Int
    let grantedReward: Int
    let rejectedReward: Int
    let answeredCount: Int
    let qualityTier: String
    let answerStatusCounts: [String: Int]
    let rewardStatusCounts: [String: Int]
    let rewardItems: [RewardLedgerItem]
    let lightEvents: [UserLightEvent]

    static let empty = UserDashboardSnapshot(
        pendingReward: 0,
        grantedReward: 0,
        rejectedReward: 0,
        answeredCount: 0,
        qualityTier: "new",
        answerStatusCounts: [:],
        rewardStatusCounts: [:],
        rewardItems: [],
        lightEvents: []
    )
}

struct UserDashboardSnapshotResult: Sendable {
    let snapshot: UserDashboardSnapshot
    let notice: ServiceNotice?
}

enum RewardLedgerStatus: String, Codable, Hashable, Sendable {
    case pending
    case granted
    case rejected

    init(rawStatus: String) {
        switch rawStatus {
        case "granted", "accepted":
            self = .granted
        case "rejected":
            self = .rejected
        default:
            self = .pending
        }
    }

    var label: String {
        switch self {
        case .pending:
            "待确认"
        case .granted:
            "已获得"
        case .rejected:
            "未采用"
        }
    }

    var icon: String {
        switch self {
        case .pending:
            "clock"
        case .granted:
            "checkmark.seal"
        case .rejected:
            "minus.circle"
        }
    }
}

struct RewardLedgerItem: Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let subtitle: String
    let valueLabel: String
    let status: RewardLedgerStatus
    let createdAt: String?
}

enum SubmittedAnswerStatus: String, Codable, Hashable, Sendable {
    case pending
    case accepted
    case rejected

    var label: String {
        switch self {
        case .pending:
            "待采纳"
        case .accepted:
            "已采纳"
        case .rejected:
            "未采用"
        }
    }
}

struct SubmittedAnswerRecord: Identifiable, Hashable, Codable, Sendable {
    let id: UUID
    let helpRequestId: UUID
    let questionTitle: String
    let questionContext: String
    let text: String
    let rewardLabel: String
    let status: SubmittedAnswerStatus
    let timeLabel: String

    init(
        id: UUID = UUID(),
        helpRequestId: UUID,
        questionTitle: String,
        questionContext: String,
        text: String,
        rewardLabel: String,
        status: SubmittedAnswerStatus = .pending,
        timeLabel: String = "刚刚"
    ) {
        self.id = id
        self.helpRequestId = helpRequestId
        self.questionTitle = questionTitle
        self.questionContext = questionContext
        self.text = text
        self.rewardLabel = rewardLabel
        self.status = status
        self.timeLabel = timeLabel
    }
}

struct ProfileAPIService: Sendable {
    private let baseURL = AppAPIEnvironment.baseURL
    private let deviceUid = DeviceIdentity.uid

    func fetchSnapshot() async -> UserDashboardSnapshot {
        await fetchSnapshotResult().snapshot
    }

    func fetchSnapshotResult() async -> UserDashboardSnapshotResult {
        var firstError: Error?
        let rewards: V1ProfileRewardsResponse?
        let quality: V1ProfileAnswererQualityResponse?
        let lights: V1ProfileLightEventsResponse?

        do {
            rewards = try await fetchRewards()
        } catch {
            firstError = firstError ?? error
            rewards = nil
        }

        do {
            quality = try await fetchAnswererQuality()
        } catch {
            firstError = firstError ?? error
            quality = nil
        }

        do {
            lights = try await fetchLightEvents()
        } catch {
            firstError = firstError ?? error
            lights = nil
        }

        let snapshot = UserDashboardSnapshot(
            pendingReward: rewards?.pendingValue ?? 0,
            grantedReward: rewards?.grantedValue ?? 0,
            rejectedReward: rewards?.rejectedValue ?? 0,
            answeredCount: quality?.answers.submittedCount ?? 0,
            qualityTier: quality?.quality.tier ?? "new",
            answerStatusCounts: quality?.answers.statusCounts ?? [:],
            rewardStatusCounts: quality?.rewards?.statusCounts ?? [:],
            rewardItems: (rewards?.items ?? []).map(\.ledgerItem),
            lightEvents: (lights?.items ?? []).map { item in
                UserLightEvent(
                    id: item.id,
                    kind: item.kind ?? item.type,
                    title: item.title ?? "有新消息",
                    body: item.body ?? item.message ?? "皮皮有新进展。",
                    cardId: UUID(uuidString: item.cardId ?? ""),
                    helpCardId: UUID(uuidString: item.helpCardId ?? ""),
                    createdAt: item.createdAt
                )
            }
        )

        return UserDashboardSnapshotResult(
            snapshot: snapshot,
            notice: firstError.map(MockData.profileSnapshotUnavailableNotice(error:))
        )
    }

    private func fetchRewards() async throws -> V1ProfileRewardsResponse {
        var components = URLComponents(url: endpoint("/v1/rewards/me"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "device_uid", value: deviceUid)]
        guard let url = components.url else { throw BackendServiceError.decoding("invalid rewards URL", "") }
        return try await perform(URLRequest(url: url))
    }

    private func fetchAnswererQuality() async throws -> V1ProfileAnswererQualityResponse {
        var components = URLComponents(url: endpoint("/v1/answerers/me/quality"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "device_uid", value: deviceUid)]
        guard let url = components.url else { throw BackendServiceError.decoding("invalid quality URL", "") }
        return try await perform(URLRequest(url: url))
    }

    private func fetchLightEvents() async throws -> V1ProfileLightEventsResponse {
        var components = URLComponents(url: endpoint("/v1/light-events"), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "device_uid", value: deviceUid),
            URLQueryItem(name: "limit", value: "10")
        ]
        guard let url = components.url else { throw BackendServiceError.decoding("invalid lights URL", "") }
        return try await perform(URLRequest(url: url))
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        var request = authorized(request)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            if status == 401, await AuthAPIService().refreshIfPossible() {
                request = authorized(request)
                let (retryData, retryResponse) = try await URLSession.shared.data(for: request)
                if let retryHTTP = retryResponse as? HTTPURLResponse, (200..<300).contains(retryHTTP.statusCode) {
                    return try JSONDecoder().decode(Response.self, from: retryData)
                }
            }
            let body = String(data: data, encoding: .utf8) ?? ""
            throw BackendServiceError.httpStatus(status, body)
        }
        return try JSONDecoder().decode(Response.self, from: data)
    }

    private func authorized(_ request: URLRequest) -> URLRequest {
        var request = request
        if let token = AuthTokenStore.accessToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }
}

private struct V1ProfileRewardsResponse: Decodable {
    let pendingValue: Int
    let grantedValue: Int
    let rejectedValue: Int
    let items: [V1ProfileRewardItem]

    enum CodingKeys: String, CodingKey {
        case pendingValue = "pending_value"
        case grantedValue = "granted_value"
        case rejectedValue = "rejected_value"
        case items
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        pendingValue = try container.decodeIfPresent(Int.self, forKey: .pendingValue) ?? 0
        grantedValue = try container.decodeIfPresent(Int.self, forKey: .grantedValue) ?? 0
        rejectedValue = try container.decodeIfPresent(Int.self, forKey: .rejectedValue) ?? 0
        items = try container.decodeIfPresent([V1ProfileRewardItem].self, forKey: .items) ?? []
    }
}

private struct V1ProfileRewardItem: Decodable {
    let id: String
    let type: String?
    let label: String?
    let value: Int
    let status: String
    let helpCardId: String?
    let helpAnswerId: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case label
        case value
        case status
        case helpCardId = "help_card_id"
        case helpAnswerId = "help_answer_id"
        case createdAt = "created_at"
    }

    var ledgerItem: RewardLedgerItem {
        let normalizedStatus = RewardLedgerStatus(rawStatus: status)
        let rewardLabel = label?.isEmpty == false ? label! : "+\(value)"
        return RewardLedgerItem(
            id: helpCardId ?? helpAnswerId ?? id,
            title: "来一句奖励",
            subtitle: normalizedStatus == .pending ? "等待对方采纳" : "来自一次来一句回答",
            valueLabel: rewardLabel,
            status: normalizedStatus,
            createdAt: createdAt
        )
    }
}

private struct V1ProfileAnswererQualityResponse: Decodable {
    let quality: V1ProfileQuality
    let answers: V1ProfileAnswers
    let rewards: V1ProfileAnswerRewards?
}

private struct V1ProfileQuality: Decodable {
    let tier: String
}

private struct V1ProfileAnswers: Decodable {
    let submittedCount: Int
    let statusCounts: [String: Int]

    enum CodingKeys: String, CodingKey {
        case submittedCount = "submitted_count"
        case statusCounts = "status_counts"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        submittedCount = try container.decodeIfPresent(Int.self, forKey: .submittedCount) ?? 0
        statusCounts = try container.decodeIfPresent([String: Int].self, forKey: .statusCounts) ?? [:]
    }
}

private struct V1ProfileAnswerRewards: Decodable {
    let pendingCount: Int
    let grantedCount: Int
    let rejectedCount: Int
    let statusCounts: [String: Int]

    enum CodingKeys: String, CodingKey {
        case pendingCount = "pending_count"
        case grantedCount = "granted_count"
        case rejectedCount = "rejected_count"
        case statusCounts = "status_counts"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        pendingCount = try container.decodeIfPresent(Int.self, forKey: .pendingCount) ?? 0
        grantedCount = try container.decodeIfPresent(Int.self, forKey: .grantedCount) ?? 0
        rejectedCount = try container.decodeIfPresent(Int.self, forKey: .rejectedCount) ?? 0
        statusCounts = try container.decodeIfPresent([String: Int].self, forKey: .statusCounts) ?? [
            "pending": pendingCount,
            "granted": grantedCount,
            "rejected": rejectedCount
        ]
    }
}

private struct V1ProfileLightEventsResponse: Decodable {
    let items: [V1ProfileLightEvent]
}

private struct V1ProfileLightEvent: Decodable {
    let id: String
    let kind: String?
    let type: String?
    let title: String?
    let body: String?
    let message: String?
    let cardId: String?
    let helpCardId: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case kind
        case type
        case title
        case body
        case message
        case cardId = "card_id"
        case helpCardId = "help_card_id"
        case createdAt = "created_at"
    }
}

private enum DeviceIdentity {
    static let uid: String = {
        let key = "just_pick_this_device_uid"
        if let existing = KeychainStore.string(for: key), !existing.isEmpty {
            return existing
        }
        if let existing = UserDefaults.standard.string(forKey: key), !existing.isEmpty {
            KeychainStore.set(existing, for: key)
            return existing
        }

        let generated = "ios-\(UUID().uuidString)"
        UserDefaults.standard.set(generated, forKey: key)
        KeychainStore.set(generated, for: key)
        return generated
    }()
}

enum AuthTokenStore {
    private static let accessKey = "auth_access_token"
    private static let refreshKey = "auth_refresh_token"
    private static let emailKey = "auth_email"
    private static let displayNameKey = "auth_display_name"

    static var accessToken: String? {
        get { KeychainStore.string(for: accessKey) }
        set { KeychainStore.setOrDelete(newValue, for: accessKey) }
    }

    static var refreshToken: String? {
        get { KeychainStore.string(for: refreshKey) }
        set { KeychainStore.setOrDelete(newValue, for: refreshKey) }
    }

    static var email: String? {
        get { KeychainStore.string(for: emailKey) }
        set { KeychainStore.setOrDelete(newValue, for: emailKey) }
    }

    static var displayName: String? {
        get { KeychainStore.string(for: displayNameKey) }
        set { KeychainStore.setOrDelete(newValue, for: displayNameKey) }
    }

    static func clear() {
        KeychainStore.delete(accessKey)
        KeychainStore.delete(refreshKey)
        KeychainStore.delete(emailKey)
        KeychainStore.delete(displayNameKey)
    }
}

private enum KeychainStore {
    private static let service = "com.justpickthis.pipii"

    static func string(for key: String) -> String? {
        var query = baseQuery(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func setOrDelete(_ value: String?, for key: String) {
        if let value, !value.isEmpty {
            set(value, for: key)
        } else {
            delete(key)
        }
    }

    static func set(_ value: String, for key: String) {
        let data = Data(value.utf8)
        var query = baseQuery(key)
        let attributes = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            query[kSecValueData as String] = data
            SecItemAdd(query as CFDictionary, nil)
        }
    }

    static func delete(_ key: String) {
        SecItemDelete(baseQuery(key) as CFDictionary)
    }

    private static func baseQuery(_ key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]
    }
}

private struct V1AuthRequestCodeRequest: Encodable {
    let email: String
    let deviceId: String
    let platform: String
    let appVersion: String

    enum CodingKeys: String, CodingKey {
        case email
        case deviceId = "device_id"
        case platform
        case appVersion = "app_version"
    }
}

private struct V1AuthRequestCodeResponse: Decodable {
    let ok: Bool
}

private struct V1AuthVerifyCodeRequest: Encodable {
    let email: String
    let code: String
    let deviceId: String
    let platform: String
    let appVersion: String

    enum CodingKeys: String, CodingKey {
        case email
        case code
        case deviceId = "device_id"
        case platform
        case appVersion = "app_version"
    }
}

private struct V1AuthVerifyCodeResponse: Decodable {
    let user: V1AuthUser
    let tokens: V1AuthTokens
}

private struct V1AuthRefreshRequest: Encodable {
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

private struct V1AuthUpdateMeRequest: Encodable {
    let displayName: String

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
    }
}

private struct V1AuthMeResponse: Decodable {
    let user: V1AuthUser
}

private struct V1AuthRefreshResponse: Decodable {
    let tokens: V1AuthTokens
}

private struct V1AuthLogoutResponse: Decodable {
    let ok: Bool
}

private struct V1AuthDeleteMeResponse: Decodable {
    let ok: Bool
    let deleted: Bool?
}

private struct V1AuthUser: Decodable {
    let id: String
    let email: String?
    let displayName: String

    enum CodingKeys: String, CodingKey {
        case id
        case email
        case displayName = "display_name"
    }
}

private struct V1AuthTokens: Decodable {
    let accessToken: String
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
    }
}

private struct V1BootstrapRequest: Encodable {
    let deviceId: String
    let platform: String
    let appVersion: String

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case platform
        case appVersion = "app_version"
    }
}

private struct V1BootstrapResponse: Decodable {
    let conversationId: String

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
    }
}

private struct V1ChatTurnRequest: Encodable {
    let message: String
    let conversationId: String?
    let deviceId: String
    let clientContext: V1ClientContext
    let metadata: [String: String]

    enum CodingKeys: String, CodingKey {
        case message
        case conversationId = "conversation_id"
        case deviceId = "device_id"
        case clientContext = "client_context"
        case metadata
    }
}

private struct V1ClientContext: Encodable {
    let source: String
    let location: V1ClientLocation?
    let decisionLocation: V1DecisionLocationContext?

    enum CodingKeys: String, CodingKey {
        case source
        case location
        case decisionLocation = "decision_location"
    }
}

struct V1ClientLocation: Encodable {
    let latitude: Double
    let longitude: Double
    let horizontalAccuracy: Double
    let capturedAt: String
    let provider: String
    let coordType: String

    enum CodingKeys: String, CodingKey {
        case latitude
        case longitude
        case horizontalAccuracy = "horizontal_accuracy"
        case capturedAt = "captured_at"
        case provider
        case coordType = "coord_type"
    }

    init(location: CLLocation) {
        self.latitude = location.coordinate.latitude
        self.longitude = location.coordinate.longitude
        self.horizontalAccuracy = max(location.horizontalAccuracy, 0)
        self.capturedAt = ISO8601DateFormatter().string(from: location.timestamp)
        self.provider = "ios_core_location"
        self.coordType = "ios_core_location"
    }

    init?(context: DecisionLocationContext) {
        guard let latitude = context.latitude, let longitude = context.longitude else {
            return nil
        }

        self.latitude = latitude
        self.longitude = longitude
        self.horizontalAccuracy = 0
        self.capturedAt = ISO8601DateFormatter().string(from: Date())
        self.provider = context.source == "current" ? "ios_core_location" : context.source
        self.coordType = context.source == "current" ? "ios_core_location" : "manual_hint"
    }
}

private struct V1DecisionLocationContext: Encodable {
    let label: String
    let city: String?
    let area: String?
    let latitude: Double?
    let longitude: Double?
    let source: String

    init(context: DecisionLocationContext) {
        self.label = context.label
        self.city = context.city
        self.area = context.area
        self.latitude = context.latitude
        self.longitude = context.longitude
        self.source = context.source
    }
}

@MainActor
final class DeviceLocationProvider: NSObject, @preconcurrency CLLocationManagerDelegate {
    static let shared = DeviceLocationProvider()

    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<V1ClientLocation?, Never>?
    private var timeoutTask: Task<Void, Never>?

    private override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        manager.distanceFilter = 50
    }

    func currentLocationPayload() async -> V1ClientLocation? {
        guard CLLocationManager.locationServicesEnabled() else { return nil }

        return await withCheckedContinuation { continuation in
            finish(nil)
            self.continuation = continuation
            timeoutTask?.cancel()
            timeoutTask = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                await MainActor.run {
                    self?.finish(nil)
                }
            }

            switch manager.authorizationStatus {
            case .notDetermined:
                manager.requestWhenInUseAuthorization()
            case .authorizedAlways, .authorizedWhenInUse:
                manager.requestLocation()
            case .denied, .restricted:
                finish(nil)
            @unknown default:
                finish(nil)
            }
        }
    }

    func currentDecisionLocation() async -> DecisionLocationContext? {
        guard let payload = await currentLocationPayload() else { return nil }
        let location = CLLocation(latitude: payload.latitude, longitude: payload.longitude)
        let placemarks = try? await CLGeocoder().reverseGeocodeLocation(location)
        let placemark = placemarks?.first
        let city = placemark?.locality ?? placemark?.administrativeArea
        let area = placemark?.subLocality ?? placemark?.name
        let labelParts = [city, area]
            .compactMap { value in
                value?.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .filter { !$0.isEmpty }
        let label = labelParts.isEmpty ? "当前位置" : labelParts.joined(separator: " · ")

        return DecisionLocationContext(
            label: label,
            city: city,
            area: area,
            latitude: payload.latitude,
            longitude: payload.longitude,
            source: "current"
        )
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            manager.requestLocation()
        case .denied, .restricted:
            finish(nil)
        case .notDetermined:
            break
        @unknown default:
            finish(nil)
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else {
            finish(nil)
            return
        }
        finish(V1ClientLocation(location: location))
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(nil)
    }

    private func finish(_ payload: V1ClientLocation?) {
        timeoutTask?.cancel()
        timeoutTask = nil
        continuation?.resume(returning: payload)
        continuation = nil
    }
}

private struct V1ChatTurnResponse: Decodable {
    let conversationId: String
    let userTurnId: String?
    let assistantMessage: String?
    let cards: [V1CardSummary]?
    let helpCards: [V1HelpCardSummary]?

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
        case userTurnId = "user_turn_id"
        case assistantMessage = "assistant_message"
        case cards
        case helpCards = "help_cards"
    }

    func result(for query: String) -> RecommendationResult {
        let decision: RecommendationDecision
        if let card = cards?.first {
            decision = .top1(card.model(query: query))
        } else if let helpCard = helpCards?.first {
            decision = .ask(helpCard.model(fallbackTitle: query))
        } else {
            decision = .none
        }

        return RecommendationResult(
            sessionId: UUID(uuidString: conversationId),
            questionId: questionId,
            history: [],
            decision: decision,
            serviceNotice: notice
        )
    }

    private var notice: ServiceNotice? {
        guard cards?.isEmpty ?? true, helpCards?.isEmpty ?? true else { return nil }
        guard let assistantMessage else { return nil }
        let trimmed = assistantMessage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return ServiceNotice(title: "皮皮", detail: trimmed)
    }

    private var questionId: UUID? {
        if let questionId = cards?.first?.metadata?.questionId {
            return questionId
        }
        return helpCards?.first?.metadata?.questionId ?? UUID(uuidString: userTurnId ?? "")
    }
}

private struct V1CardSummary: Decodable {
    let id: UUID?
    let title: String
    let subtitle: String?
    let oneLiner: String?
    let bullets: [String]?
    let warning: String?
    let followups: [String]?
    let status: String?
    let image: V1ImageAsset?
    let metadata: V1CardMetadata?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case subtitle
        case oneLiner = "one_liner"
        case bullets
        case warning
        case followups
        case status
        case image
        case metadata
    }

    func model(query fallbackQuery: String) -> TopPick {
        let resolvedReason = clean(oneLiner, fallback: "我把已有线索收成一个选择。")
        let resolvedFollowups = removeAskHuman(
            from: cleanArrayAllowingEmpty(followups)
        )

        return TopPick(
            cardId: id,
            query: fallbackQuery,
            preface: "别查了,就这个。",
            title: clean(title, fallback: "先选一个最稳的"),
            subtitle: clean(subtitle, fallback: "不用再比较。"),
            reason: resolvedReason,
            bullets: cleanArrayAllowingEmpty(bullets),
            warning: clean(warning, fallback: ""),
            followups: resolvedFollowups,
            referenceImage: image?.model
        )
    }
}

private struct V1CardMetadata: Decodable {
    let questionId: UUID?

    enum CodingKeys: String, CodingKey {
        case questionId = "question_id"
    }
}

private struct V1ImageAsset: Decodable {
    let id: UUID?
    let url: String?
    let sourceUrl: String?
    let sourceDomain: String?
    let caption: String?
    let verified: Bool
    let isAiGenerated: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case url
        case sourceUrl = "source_url"
        case sourceDomain = "source_domain"
        case caption
        case verified
        case isAiGenerated = "is_ai_generated"
    }

    var model: ReferenceImage? {
        guard let url, verified, !isAiGenerated else { return nil }
        return ReferenceImage(
            url: url,
            sourceURL: sourceUrl,
            sourceDomain: sourceDomain,
            caption: caption,
            isAiGenerated: isAiGenerated
        )
    }
}

private struct V1HelpCardSummary: Decodable {
    let id: UUID?
    let title: String?
    let prompt: String
    let status: String?
    let contextText: String?
    let oneLiner: String?
    let reward: V1RewardPayload?
    let answerCount: Int?
    let card: V1CardSummary?
    let metadata: V1HelpCardMetadata?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case prompt
        case status
        case contextText = "context_text"
        case oneLiner = "one_liner"
        case reward
        case answerCount = "answer_count"
        case card
        case metadata
        case createdAt = "created_at"
    }

    func model(fallbackTitle: String) -> HelpRequest {
        let resolvedTitle = clean(title, fallback: clean(prompt, fallback: fallbackTitle))
        let finalPick = card?.model(query: resolvedTitle)

        return HelpRequest(
            id: id ?? UUID(),
            title: resolvedTitle,
            context: clean(contextText, fallback: clean(oneLiner, fallback: "这题不硬选 · 等懂的人来一句")),
            rewardLabel: reward?.label ?? "+10",
            answerCount: answerCount ?? metadata?.answerCount ?? 0,
            status: helpRequestStatus(from: status),
            answers: [],
            finalPick: finalPick,
            createdAt: createdAt
        )
    }

    private func helpRequestStatus(from status: String?) -> HelpRequestStatus {
        switch status {
        case "draft":
            .draft
        case "published", "collecting", "open":
            .published
        case "final_ready", "answered":
            .answered
        case "closed":
            .closed
        case "completed":
            .completed
        default:
            .draft
        }
    }
}

private struct V1HelpCardDetailEnvelope: Decodable {
    let summary: V1HelpCardSummary

    enum CodingKeys: String, CodingKey {
        case helpCard = "help_card"
    }

    init(from decoder: Decoder) throws {
        let container = try? decoder.container(keyedBy: CodingKeys.self)
        if let summary = try container?.decodeIfPresent(V1HelpCardSummary.self, forKey: .helpCard) {
            self.summary = summary
        } else {
            self.summary = try V1HelpCardSummary(from: decoder)
        }
    }
}

private struct V1RewardPayload: Decodable {
    let label: String?
    let value: Int?
    let status: String?
}

private struct V1HelpCardMetadata: Decodable {
    let questionId: UUID?
    let answerCount: Int?
    let minAnswersRequired: Int?

    enum CodingKeys: String, CodingKey {
        case questionId = "question_id"
        case answerCount = "answer_count"
        case minAnswersRequired = "min_answers_required"
    }
}

private struct V1HelpFeedResponse: Decodable {
    let items: [V1HelpCardSummary]
}

private struct V1HelpCardOneLinerRequest: Encodable {
    let text: String
    let deviceId: String

    enum CodingKeys: String, CodingKey {
        case text
        case deviceId = "device_id"
    }
}

private struct V1HelpCardOneLinerResponse: Decodable {
    let helpCardId: String
    let answerId: UUID?
    let reward: V1RewardPayload?
    let toast: String?
    let shouldAdvance: Bool?
    let metadata: V1OneLinerMetadata?

    enum CodingKeys: String, CodingKey {
        case helpCardId = "help_card_id"
        case answerId = "answer_id"
        case reward
        case toast
        case shouldAdvance = "should_advance"
        case metadata
    }

    var isFinalReady: Bool {
        metadata?.finalizationReady == true
    }
}

private struct V1OneLinerMetadata: Decodable {
    let finalizationReady: Bool?

    enum CodingKeys: String, CodingKey {
        case finalizationReady = "finalization_ready"
    }
}

private struct V1HelpCardSkipRequest: Encodable {
    let deviceId: String
    let reason: String
    let metadata: [String: String]

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case reason
        case metadata
    }
}

private struct V1HelpCardSkipResponse: Decodable {
    let ok: Bool
    let helpCardId: String

    enum CodingKeys: String, CodingKey {
        case ok
        case helpCardId = "help_card_id"
    }
}

private struct V1HelpCardFinalAcceptRequest: Encodable {
    let deviceId: String
    let reason: String
    let metadata: [String: String]

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case reason
        case metadata
    }
}

private struct V1HelpCardFinalAcceptResponse: Decodable {
    let helpCardId: String
    let cardId: String?
    let accepted: Bool

    enum CodingKeys: String, CodingKey {
        case helpCardId = "help_card_id"
        case cardId = "card_id"
        case accepted
    }
}

private struct V1LightEventsResponse: Decodable {
    let items: [V1LightEvent]
}

private struct V1LightEvent: Decodable {
    let helpCardId: String?

    enum CodingKeys: String, CodingKey {
        case helpCardId = "help_card_id"
    }
}

private struct V1CardAcceptRequest: Encodable {
    let metadata: [String: String]
}

private struct V1CardFeedbackRequest: Encodable {
    let deviceId: String
    let reason: String
    let tags: [String]
    let metadata: [String: String]

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case reason
        case tags
        case metadata
    }
}

private struct V1CardAcceptResponse: Decodable {
    let cardId: String
    let accepted: Bool

    enum CodingKeys: String, CodingKey {
        case cardId = "card_id"
        case accepted
    }
}

private struct V1CardFeedbackResponse: Decodable {
    let cardId: String
    let accepted: Bool

    enum CodingKeys: String, CodingKey {
        case cardId = "card_id"
        case accepted
    }
}

struct MockCloudRecommendationService: RecommendationService {
    func submit(query: String, sessionId: UUID?, locationContext: DecisionLocationContext?) async -> RecommendationResult {
        try? await Task.sleep(for: .milliseconds(650))

        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if shouldAskHuman(for: trimmed) {
            return RecommendationResult(
                sessionId: sessionId ?? UUID(),
                questionId: UUID(),
                history: [],
                decision: .ask(MockData.helpRequest(for: trimmed)),
                serviceNotice: nil
            )
        }

        return RecommendationResult(
            sessionId: sessionId ?? UUID(),
            questionId: UUID(),
            history: [],
            decision: .top1(MockData.topPick(for: trimmed)),
            serviceNotice: nil
        )
    }

    func publish(_ request: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> PublishHelpResult {
        var updated = request
        updated.status = .published
        return PublishHelpResult(request: updated, didPublish: true, notice: nil)
    }

    func refresh(_ request: HelpRequest) async -> HelpRequest {
        request
    }

    func fetchHelpRequest(id: UUID) async -> HelpRequest? {
        nil
    }

    func myHelpRequests(limit: Int) async -> MyHelpRequestsResult {
        MyHelpRequestsResult(requests: [MockData.defaultHelpRequest], notice: nil)
    }

    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest] {
        [MockData.defaultHelpRequest]
    }

    func answer(_ text: String, for request: HelpRequest) async -> SubmitHelpAnswerResult {
        var updated = request
        updated.answers.append(HumanAnswer(text: text, nickname: "路过的人", timeLabel: "刚刚"))
        updated.answerCount += 1
        updated.status = .answered
        return SubmitHelpAnswerResult(request: updated, didSubmit: true, notice: nil)
    }

    func skip(_ request: HelpRequest, reason: String) async -> Bool {
        true
    }

    func acceptCard(id: UUID?) async -> Bool {
        true
    }

    func sendCardFeedback(id: UUID?, action: CardFeedbackAction, reason: String) async -> Bool {
        id != nil && !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> CompleteQuestionResult {
        CompleteQuestionResult(didComplete: helpRequestId != nil, history: [], notice: nil)
    }

    private func shouldAskHuman(for query: String) -> Bool {
        let uncertainKeywords = ["韩国", "首尔", "明洞", "小众", "求一个", "真人", "不敢", "失败", "没结果", "no result", "fail"]
        return uncertainKeywords.contains { keyword in
            query.localizedCaseInsensitiveContains(keyword)
        }
    }
}

private struct RecommendationRequest: Encodable {
    let query: String
    let sessionId: String?
}

private struct HelpRequestPayload: Encodable {
    let id: String
    let sessionId: String?
    let questionId: String?
    let title: String
    let context: String
    let status: HelpRequestStatus
    let answers: [HumanAnswerPayload]

    init(helpRequest: HelpRequest, status: HelpRequestStatus, sessionId: UUID?, questionId: UUID?) {
        self.id = helpRequest.id.uuidString
        self.sessionId = sessionId?.uuidString
        self.questionId = questionId?.uuidString
        self.title = helpRequest.title
        self.context = helpRequest.context
        self.status = status
        self.answers = helpRequest.answers.map(HumanAnswerPayload.init)
    }
}

private struct HumanAnswerPayload: Encodable {
    let id: String
    let text: String
    let nickname: String
    let timeLabel: String

    init(answer: HumanAnswer) {
        self.id = answer.id.uuidString
        self.text = answer.text
        self.nickname = answer.nickname
        self.timeLabel = answer.timeLabel
    }
}

private struct AnswerPayload: Encodable {
    let text: String
    let nickname: String
}

private struct CompleteQuestionPayload: Encodable {
    let helpRequestId: String?
    let source: String
}

private struct SessionEnvelope: Decodable {
    let session: SessionResponse
}

private struct SessionResponse: Decodable {
    let questions: [QuestionHistoryResponse]
}

private struct RecommendationResponse: Decodable {
    let sessionId: UUID?
    let questionId: UUID?
    let history: [QuestionHistoryResponse]?
    let kind: String
    let topPick: TopPickResponse?
    let helpRequest: HelpRequestResponse?

    func result(for query: String) -> RecommendationResult {
        let decision: RecommendationDecision
        switch kind {
        case "top1":
            guard let topPick else {
                decision = .ask(MockData.backendFallbackHelpRequest(for: query))
                break
            }
            decision = .top1(topPick.model(query: query))
        case "ask":
            guard let helpRequest else {
                decision = .ask(MockData.backendFallbackHelpRequest(for: query))
                break
            }
            decision = .ask(helpRequest.model(fallbackTitle: query))
        default:
            decision = .none
        }

        return RecommendationResult(
            sessionId: sessionId,
            questionId: questionId,
            history: history?.compactMap(\.model) ?? [],
            decision: decision,
            serviceNotice: nil
        )
    }
}

private struct QuestionHistoryResponse: Decodable {
    let id: UUID?
    let query: String?
    let status: String?
    let helpRequestId: UUID?
    let topPick: TopPickResponse?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case query
        case status
        case helpRequestId = "help_request_id"
        case topPick = "top_pick"
        case createdAt = "created_at"
    }

    var model: QuestionHistory? {
        guard let id, let query, let status else { return nil }
        return QuestionHistory(
            id: id,
            query: query,
            status: status,
            helpRequestId: helpRequestId,
            topPick: topPick?.model(query: query),
            createdAt: createdAt
        )
    }
}

private struct HelpRequestEnvelope: Decodable {
    let helpRequest: HelpRequestResponse
}

private struct HelpRequestListEnvelope: Decodable {
    let helpRequests: [HelpRequestResponse]
}

private struct TopPickResponse: Decodable {
    let query: String?
    let preface: String?
    let title: String?
    let subtitle: String?
    let reason: String?
    let bullets: [String]?
    let warning: String?
    let followups: [String]?

    func model(query fallbackQuery: String) -> TopPick {
        let resolvedFollowups = removeAskHuman(
            from: cleanArray(followups, fallback: ["为什么?", "换个小众的"])
        )

        return TopPick(
            cardId: nil,
            query: clean(query, fallback: fallbackQuery),
            preface: clean(preface, fallback: "别查了,就这个。"),
            title: clean(title, fallback: "先选一个最稳的"),
            subtitle: clean(subtitle, fallback: "不用再比较。"),
            reason: clean(reason, fallback: "你已经给了位置和目的,这题先做一个低后悔选择。"),
            bullets: cleanArray(bullets, fallback: MockData.genericTopPick(for: fallbackQuery).bullets),
            warning: clean(warning, fallback: "如果你明确不喜欢这个类型,就别选。"),
            followups: resolvedFollowups.isEmpty ? ["为什么?", "换个小众的"] : resolvedFollowups,
            referenceImage: nil
        )
    }
}

private struct HelpRequestResponse: Decodable {
    let id: UUID?
    let title: String?
    let context: String?
    let status: HelpRequestStatus?
    let answers: [HumanAnswerResponse]?

    func model(fallbackTitle: String) -> HelpRequest {
        HelpRequest(
            id: id ?? UUID(),
            title: clean(title, fallback: fallbackTitle),
            context: clean(context, fallback: "这题不硬选 · 等懂的人来一句"),
            status: status ?? .draft,
            answers: answers?.map(\.model) ?? []
        )
    }
}

private struct HumanAnswerResponse: Decodable {
    let id: UUID?
    let text: String?
    let nickname: String?
    let timeLabel: String?

    var model: HumanAnswer {
        HumanAnswer(
            id: id ?? UUID(),
            text: clean(text, fallback: ""),
            nickname: clean(nickname, fallback: "路过的人"),
            timeLabel: clean(timeLabel, fallback: "刚刚")
        )
    }
}

@MainActor
@Observable
final class AppSession {
    private(set) var sessionId: UUID?
    private(set) var currentQuestionId: UUID?
    private(set) var currentQuery = ""
    private(set) var currentTopPick: TopPick?
    private(set) var currentHelpRequest: HelpRequest?
    private(set) var history: [QuestionHistory] = []
    private(set) var favoriteChoices: [QuestionHistory] = []
    private(set) var hiddenFavoriteChoiceIds: Set<UUID> = []
    private(set) var submittedAnswers: [SubmittedAnswerRecord] = []
    private(set) var myHelpRequests: [HelpRequest] = []
    private(set) var answerQueue: [HelpRequest] = []
    private(set) var answerTarget: HelpRequest?
    private(set) var submitState: SubmitState = .idle
    private(set) var serviceNotice: ServiceNotice?

    @ObservationIgnored private let service: any RecommendationService
    @ObservationIgnored private let documentationDemo: String?
    @ObservationIgnored private static let historyKey = "question_history_v1"
    @ObservationIgnored private static let favoriteChoicesKey = "favorite_choices_v1"
    @ObservationIgnored private static let hiddenFavoriteChoiceIDsKey = "hidden_favorite_choice_ids_v1"
    @ObservationIgnored private static let submittedAnswersKey = "submitted_answers_v1"

    init(service: any RecommendationService, documentationDemo: String? = nil) {
        self.service = service
        self.documentationDemo = documentationDemo
        restoreLocalCollections()

        #if DEBUG
        applyDocumentationDemo(documentationDemo)
        #endif
    }

    var isSubmitting: Bool {
        submitState == .loading
    }

    var topPick: TopPick {
        currentTopPick ?? MockData.genericTopPick(for: currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery)
    }

    var helpRequest: HelpRequest {
        currentHelpRequest ?? MockData.defaultHelpRequest
    }

    var answerRequest: HelpRequest? {
        answerTarget ?? answerQueue.first
    }

    var nextAnswerRequest: HelpRequest? {
        guard let current = answerRequest else { return nil }
        return answerQueue.first { $0.id != current.id }
    }

    func startNewConversation() {
        sessionId = nil
        currentQuestionId = nil
        currentQuery = ""
        currentTopPick = nil
        currentHelpRequest = nil
        serviceNotice = nil
        submitState = .idle
    }

    func clearLocalUserData() {
        sessionId = nil
        currentQuestionId = nil
        currentQuery = ""
        currentTopPick = nil
        currentHelpRequest = nil
        history = []
        favoriteChoices = []
        hiddenFavoriteChoiceIds = []
        submittedAnswers = []
        myHelpRequests = []
        answerQueue = []
        answerTarget = nil
        serviceNotice = nil
        submitState = .idle

        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: Self.historyKey)
        defaults.removeObject(forKey: Self.favoriteChoicesKey)
        defaults.removeObject(forKey: Self.hiddenFavoriteChoiceIDsKey)
        defaults.removeObject(forKey: Self.submittedAnswersKey)
        defaults.removeObject(forKey: "seen_light_event_ids")
        defaults.removeObject(forKey: "pinned_history_ids")
        defaults.removeObject(forKey: "hidden_history_ids")
        defaults.removeObject(forKey: "renamed_history_titles")
        defaults.removeObject(forKey: "recent_decision_location_labels")
        defaults.removeObject(forKey: "active_decision_location_context")
    }

    func submit(query: String, locationContext: DecisionLocationContext? = nil) async -> RecommendationDecision {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        currentQuery = trimmed
        submitState = .loading

        let result = await service.submit(query: trimmed, sessionId: sessionId, locationContext: locationContext)
        serviceNotice = result.serviceNotice
        sessionId = result.sessionId ?? sessionId
        currentQuestionId = result.questionId ?? currentQuestionId
        if !result.history.isEmpty {
            history = result.history
            persistHistory()
        } else if !result.decision.isEmpty {
            upsertLocalHistory(
                query: trimmed,
                status: status(for: result.decision),
                helpRequestId: helpRequestId(for: result.decision),
                topPick: topPick(for: result.decision)
            )
        }
        apply(result.decision)
        submitState = .idle
        return result.decision
    }

    func restoreHistoryItem(_ item: QuestionHistory) async -> HistoryDestination {
        currentQuestionId = item.id
        currentQuery = item.query

        if shouldOpenHelpRequest(for: item) {
            currentTopPick = nil
            if let helpRequestId = item.helpRequestId,
               let request = await service.fetchHelpRequest(id: helpRequestId) {
                currentHelpRequest = request
            } else {
                currentHelpRequest = fallbackHelpRequest(for: item)
            }
            return .ask
        }

        currentHelpRequest = nil
        currentTopPick = item.topPick ?? MockData.genericTopPick(for: item.query)
        return .result
    }

    func helpRequestDetail(for item: QuestionHistory) async -> HelpRequest {
        if currentHelpRequest?.id == item.helpRequestId {
            return currentHelpRequest ?? fallbackHelpRequest(for: item)
        }

        if let helpRequestId = item.helpRequestId,
           let request = await service.fetchHelpRequest(id: helpRequestId) {
            return mergedLocalHelpAnswers(into: request, historyItem: item)
        }

        return fallbackHelpRequest(for: item)
    }

    func makeHelpRequestFromCurrentTopPick() {
        let query = currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery
        let pick = topPick
        Task {
            _ = await service.sendCardFeedback(id: pick.cardId, action: .askHuman, reason: "想听真人意见")
        }
        currentHelpRequest = HelpRequest(
            title: query,
            context: "已经给过一个选择: \(pick.title) · 还想听懂的人来一句",
            status: .draft,
            answers: []
        )
    }

    func addHelpContext(_ text: String) {
        let supplement = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !supplement.isEmpty else { return }

        ensureHelpRequest()
        currentHelpRequest?.context += "\n补充: \(supplement)"
    }

    func publishCurrentRequest() async -> Bool {
        ensureHelpRequest()
        guard let request = currentHelpRequest else { return false }
        let result = await service.publish(request, sessionId: sessionId, questionId: currentQuestionId)
        currentHelpRequest = result.request
        serviceNotice = result.notice
        guard result.didPublish else { return false }
        upsertMyHelpRequest(result.request)
        upsertLocalHistory(query: result.request.title, status: "waiting_for_human", helpRequestId: result.request.id, topPick: currentTopPick)
        return true
    }

    func refreshCurrentHelpRequest() async -> Bool {
        guard let request = currentHelpRequest else { return false }
        let previousAnswerCount = request.answers.count
        let refreshed = await service.refresh(request)
        let receivedFinalPick = request.finalPick == nil && refreshed.finalPick != nil
        currentHelpRequest = refreshed
        upsertMyHelpRequest(refreshed)
        if refreshed.answers.count > previousAnswerCount || receivedFinalPick {
            upsertLocalHistory(
                query: refreshed.title,
                status: refreshed.finalPick == nil ? "answer_received" : "completed",
                helpRequestId: refreshed.id,
                topPick: refreshed.finalPick ?? currentTopPick
            )
            return true
        }
        return false
    }

    func closeCurrentHelpRequest() {
        guard currentHelpRequest != nil else { return }
        currentHelpRequest?.status = .closed
        let request = helpRequest
        upsertMyHelpRequest(request)
        upsertLocalHistory(
            query: request.title,
            status: "closed",
            helpRequestId: request.id,
            topPick: currentTopPick
        )
    }

    func loadAnswerQueue() async {
        #if DEBUG
        if documentationDemo == "answer", !answerQueue.isEmpty {
            answerTarget = answerQueue.first
            return
        }
        #endif

        let requests = await service.answerQueue(excluding: sessionId)
        answerQueue = requests
        answerTarget = requests.first
    }

    @discardableResult
    func loadMyHelpRequests() async -> ServiceNotice? {
        let result = await service.myHelpRequests(limit: 100)
        if result.notice == nil || !result.requests.isEmpty {
            myHelpRequests = result.requests
        }
        serviceNotice = result.notice
        return result.notice
    }

    func selectAnswerRequest(_ request: HelpRequest) {
        if !answerQueue.contains(where: { $0.id == request.id }) {
            answerQueue.insert(request, at: 0)
        }
        answerTarget = request
    }

    @discardableResult
    func addAnswer(_ text: String) async -> SubmitHelpAnswerResult {
        let answer = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty else {
            return SubmitHelpAnswerResult(request: nil, didSubmit: false, notice: nil)
        }

        guard let request = answerRequest else {
            return SubmitHelpAnswerResult(request: nil, didSubmit: false, notice: nil)
        }
        let result = await service.answer(answer, for: request)
        guard result.didSubmit, let updated = result.request else {
            serviceNotice = result.notice
            return result
        }
        let record = SubmittedAnswerRecord(
            helpRequestId: request.id,
            questionTitle: request.title,
            questionContext: request.context,
            text: answer,
            rewardLabel: updated.rewardLabel.isEmpty ? request.rewardLabel : updated.rewardLabel
        )
        submittedAnswers.removeAll { $0.helpRequestId == request.id }
        submittedAnswers.insert(record, at: 0)
        persistSubmittedAnswers()

        if currentHelpRequest?.id == updated.id {
            currentHelpRequest = updated
        }
        answerQueue.removeAll { $0.id == request.id }
        answerTarget = answerQueue.first
        serviceNotice = nil
        return result
    }

    func advanceAnswerRequest() {
        guard let request = answerRequest else { return }
        answerQueue.removeAll { $0.id == request.id }
        answerTarget = answerQueue.first
    }

    func skipAnswerRequest(reason: String) async {
        guard let request = answerRequest else { return }
        _ = await service.skip(request, reason: reason)
        answerQueue.removeAll { $0.id == request.id }
        answerTarget = answerQueue.first
    }

    func acceptCurrentTopPick() async -> Bool {
        let accepted = await service.acceptCard(id: currentTopPick?.cardId)
        guard accepted else {
            serviceNotice = MockData.acceptUnavailableNotice()
            return false
        }

        serviceNotice = nil
        markCurrentQuestionCompleted(remoteHistory: [])
        currentTopPick = nil
        currentQuery = ""
        return true
    }

    func saveCurrentTopPickToFavorites() {
        let query = currentQuery.isEmpty ? topPick.query : currentQuery
        let item = QuestionHistory(
            id: currentQuestionId ?? UUID(),
            query: query.isEmpty ? MockData.queryPlaceholder : query,
            status: "saved",
            helpRequestId: nil,
            topPick: currentTopPick ?? topPick,
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        favoriteChoices.removeAll { $0.id == item.id }
        hiddenFavoriteChoiceIds.remove(item.id)
        favoriteChoices.insert(item, at: 0)
        persistFavoriteState()
    }

    func removeFavoriteChoice(id: UUID) {
        favoriteChoices.removeAll { $0.id == id }
        hiddenFavoriteChoiceIds.insert(id)
        persistFavoriteState()
    }

    func restoreFavoriteChoice(_ item: QuestionHistory) {
        favoriteChoices.removeAll { $0.id == item.id }
        hiddenFavoriteChoiceIds.remove(item.id)
        favoriteChoices.insert(item, at: 0)
        persistFavoriteState()
    }

    func unhideFavoriteChoice(id: UUID) {
        hiddenFavoriteChoiceIds.remove(id)
        persistFavoriteState()
    }

    func deleteHistoryItem(id: UUID) {
        history.removeAll { $0.id == id }
        persistHistory()

        guard currentQuestionId == id else { return }
        currentQuestionId = nil
        currentQuery = ""
        currentTopPick = nil
        currentHelpRequest = nil
        serviceNotice = nil
        submitState = .idle
    }

    func restoreDeletedHistoryItem(_ item: QuestionHistory) {
        history.removeAll { $0.id == item.id }
        history.insert(item, at: 0)
        persistHistory()
    }

    @discardableResult
    func sendCurrentTopPickFeedback(action: CardFeedbackAction, reason: String) async -> Bool {
        await service.sendCardFeedback(id: currentTopPick?.cardId, action: action, reason: reason)
    }

    func acceptCurrentHelpAnswer() async -> Bool {
        let result = await service.complete(
            sessionId: sessionId,
            questionId: currentQuestionId,
            helpRequestId: currentHelpRequest?.id,
            source: "human_answer"
        )

        serviceNotice = result.notice
        guard result.didComplete else { return false }

        markCurrentQuestionCompleted(remoteHistory: result.history)
        currentHelpRequest = nil
        currentQuery = ""
        return true
    }

    private func apply(_ decision: RecommendationDecision) {
        switch decision {
        case .none:
            currentTopPick = nil
            currentHelpRequest = nil
        case .top1(let pick):
            currentTopPick = pick
            currentHelpRequest = nil
        case .ask(let request):
            currentTopPick = nil
            currentHelpRequest = request
        }
    }

    private func ensureHelpRequest() {
        guard currentHelpRequest == nil else { return }
        currentHelpRequest = MockData.helpRequest(for: currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery)
    }

    private func restoreLocalCollections() {
        let defaults = UserDefaults.standard
        if let data = defaults.data(forKey: Self.historyKey),
           let decoded = try? JSONDecoder().decode([QuestionHistory].self, from: data) {
            history = decoded
        }
        if let data = defaults.data(forKey: Self.favoriteChoicesKey),
           let decoded = try? JSONDecoder().decode([QuestionHistory].self, from: data) {
            favoriteChoices = decoded
        }
        if let data = defaults.data(forKey: Self.hiddenFavoriteChoiceIDsKey),
           let decoded = try? JSONDecoder().decode([UUID].self, from: data) {
            hiddenFavoriteChoiceIds = Set(decoded)
        }
        if let data = defaults.data(forKey: Self.submittedAnswersKey),
           let decoded = try? JSONDecoder().decode([SubmittedAnswerRecord].self, from: data) {
            submittedAnswers = decoded
        }
    }

    private func persistHistory() {
        let historyItems = Array(history.prefix(120))
        if history.count != historyItems.count {
            history = historyItems
        }
        if let data = try? JSONEncoder().encode(historyItems) {
            UserDefaults.standard.set(data, forKey: Self.historyKey)
        }
    }

    private func persistFavoriteState() {
        let defaults = UserDefaults.standard
        let favorites = Array(favoriteChoices.prefix(80))
        if let data = try? JSONEncoder().encode(favorites) {
            defaults.set(data, forKey: Self.favoriteChoicesKey)
        }
        if let data = try? JSONEncoder().encode(Array(hiddenFavoriteChoiceIds)) {
            defaults.set(data, forKey: Self.hiddenFavoriteChoiceIDsKey)
        }
    }

    private func persistSubmittedAnswers() {
        let answers = Array(submittedAnswers.prefix(80))
        if submittedAnswers.count != answers.count {
            submittedAnswers = answers
        }
        if let data = try? JSONEncoder().encode(answers) {
            UserDefaults.standard.set(data, forKey: Self.submittedAnswersKey)
        }
    }

    private func upsertLocalHistory(query: String, status: String, helpRequestId: UUID?, topPick: TopPick?) {
        if let currentQuestionId,
           let index = history.firstIndex(where: { $0.id == currentQuestionId }) {
            let existing = history[index]
            history[index] = QuestionHistory(
                id: currentQuestionId,
                query: query,
                status: status,
                helpRequestId: helpRequestId,
                topPick: topPick ?? existing.topPick,
                createdAt: existing.createdAt
            )
            persistHistory()
            return
        }

        let id = currentQuestionId ?? UUID()
        currentQuestionId = id
        history.insert(
            QuestionHistory(
                id: id,
                query: query,
                status: status,
                helpRequestId: helpRequestId,
                topPick: topPick,
                createdAt: ISO8601DateFormatter().string(from: Date())
            ),
            at: 0
        )
        persistHistory()
    }

    private func upsertMyHelpRequest(_ request: HelpRequest) {
        if let index = myHelpRequests.firstIndex(where: { $0.id == request.id }) {
            myHelpRequests[index] = request
        } else {
            myHelpRequests.insert(request, at: 0)
        }
    }

    private func status(for decision: RecommendationDecision) -> String {
        switch decision {
        case .none:
            "completed"
        case .top1:
            "top1"
        case .ask:
            "waiting_for_human"
        }
    }

    private func helpRequestId(for decision: RecommendationDecision) -> UUID? {
        switch decision {
        case .none:
            nil
        case .top1:
            nil
        case .ask(let request):
            request.id
        }
    }

    private func topPick(for decision: RecommendationDecision) -> TopPick? {
        switch decision {
        case .none:
            nil
        case .top1(let pick):
            pick
        case .ask:
            nil
        }
    }

    private func shouldOpenHelpRequest(for item: QuestionHistory) -> Bool {
        if item.helpRequestId != nil {
            return true
        }

        return item.status == "draft"
            || item.status == "waiting_for_human"
            || item.status == "answer_received"
            || item.status == "closed"
    }

    private func fallbackHelpRequest(for item: QuestionHistory) -> HelpRequest {
        let request = HelpRequest(
            id: item.helpRequestId ?? UUID(),
            title: item.query,
            context: item.status == "completed"
                ? "这题已经完成。"
                : "这题不硬选 · 等懂的人来一句",
            status: helpRequestStatus(for: item),
            answers: [],
            finalPick: item.topPick
        )
        return mergedLocalHelpAnswers(into: request, historyItem: item)
    }

    private func mergedLocalHelpAnswers(into request: HelpRequest, historyItem: QuestionHistory) -> HelpRequest {
        var merged = request
        let localAnswers = submittedAnswers
            .filter { $0.helpRequestId == historyItem.helpRequestId || $0.helpRequestId == request.id }
            .map { answer in
                HumanAnswer(
                    id: answer.id,
                    text: answer.text,
                    nickname: "我",
                    timeLabel: answer.timeLabel
                )
            }
        for answer in localAnswers where !merged.answers.contains(where: { $0.id == answer.id || $0.text == answer.text }) {
            merged.answers.append(answer)
        }
        merged.answerCount = max(merged.answerCount, merged.answers.count)
        return merged
    }

    private func helpRequestStatus(for item: QuestionHistory) -> HelpRequestStatus {
        switch item.status {
        case "closed":
            .closed
        case "completed":
            .completed
        case "answer_received":
            .answered
        case "waiting_for_human":
            .published
        default:
            .draft
        }
    }

    private func markCurrentQuestionCompleted(remoteHistory: [QuestionHistory]) {
        if !remoteHistory.isEmpty {
            history = remoteHistory
            persistHistory()
            return
        }

        let query = currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery
        upsertLocalHistory(query: query, status: "completed", helpRequestId: currentHelpRequest?.id, topPick: currentTopPick)
    }

    #if DEBUG
    private func applyDocumentationDemo(_ demo: String?) {
        guard let demo else { return }

        switch demo {
        case "result":
            currentQuery = MockData.demoQuery
            currentTopPick = MockData.topPick(for: MockData.demoQuery)
        case "ask":
            currentQuery = "在韩国逛街，不想去明洞"
            currentHelpRequest = HelpRequest(
                title: "在韩国逛街，不想去明洞",
                context: "用户说：在韩国逛街，不想去明洞。先收集懂的人一句建议。",
                status: .draft,
                answers: []
            )
        case "answer":
            let request = HelpRequest(
                title: "在韩国逛街，不想去明洞",
                context: "用户说：在韩国逛街，不想去明洞，想小众，求一个。",
                status: .published,
                answers: []
            )
            answerQueue = [request]
            answerTarget = request
        default:
            break
        }
    }
    #endif
}

enum MockData {
    static let queryPlaceholder = "我在哪,想干什么?"
    static let demoQuery = "我现在在大同喜晋道,不知道吃什么"
    static func backendUnavailableNotice(error _: Error) -> ServiceNotice {
        ServiceNotice(
            title: "皮皮",
            detail: "这轮没连上服务，原话我先留着。你可以重试，或者改一句再发。"
        )
    }

    static func publishUnavailableNotice(error _: Error) -> ServiceNotice {
        ServiceNotice(
            title: "皮皮",
            detail: "这次没发出去，草稿还在。你可以重试。"
        )
    }

    static func answerUnavailableNotice(error _: Error) -> ServiceNotice {
        ServiceNotice(
            title: "皮皮",
            detail: "这句还没提交成功，内容我留在输入框里。你可以重试。"
        )
    }

    static func acceptUnavailableNotice() -> ServiceNotice {
        ServiceNotice(
            title: "皮皮",
            detail: "这次还没采纳成功，当前结果我先留着。你可以重试。"
        )
    }

    static func profileSnapshotUnavailableNotice(error _: Error) -> ServiceNotice {
        ServiceNotice(
            title: "同步失败",
            detail: "个人数据这次没同步完整，下面可能不是最新状态。你可以重试。"
        )
    }

    static func myHelpUnavailableNotice() -> ServiceNotice {
        ServiceNotice(
            title: "同步失败",
            detail: "我的求一个这次没同步完整，下面会先显示本地记录。你可以重试。"
        )
    }

    static let defaultHelpRequest = HelpRequest(
        title: "这题先求一个",
        context: "我先帮你发出去，等懂的人来一句。"
    )

    static func genericTopPick(for query: String) -> TopPick {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? queryPlaceholder : query

        return TopPick(
            cardId: nil,
            query: resolvedQuery,
            preface: "先别纠结。",
            title: "等一个更稳的选择",
            subtitle: "这题我不硬选。",
            reason: "现在还不够确定，先收一句真人建议更稳。",
            bullets: [
                "不硬凑推荐。",
                "先等更多线索。",
                "等有人补一句再给最终答案。"
            ],
            warning: "如果你已经有明确偏好，可以直接补一句。",
            followups: ["补一句偏好", "问真人"],
            referenceImage: nil
        )
    }

    static func topPick(for query: String) -> TopPick {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? Self.demoQuery : query

        return TopPick(
            cardId: nil,
            query: resolvedQuery,
            preface: "别查了,就这个。",
            title: "刀削面 + 肉丸子",
            subtitle: "第一次来大同,就吃这个最稳。",
            reason: "你已经给了位置和目的,这题不需要再比较菜单。先吃一个地方感强、点偏概率低的组合。",
            bullets: [
                "你已经到店了,别再研究菜单。",
                "第一次来大同,要吃一个地方感强、不容易点偏的。",
                "这组比只点面更完整。"
            ],
            warning: "不爱吃面,就别选。",
            followups: ["为什么?", "换个小众的"],
            referenceImage: nil
        )
    }

    static func helpRequest(for query: String) -> HelpRequest {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? defaultHelpRequest.title : query

        if resolvedQuery.localizedCaseInsensitiveContains("韩国")
            || resolvedQuery.localizedCaseInsensitiveContains("首尔")
            || resolvedQuery.localizedCaseInsensitiveContains("明洞") {
            return defaultHelpRequest
        }

        return HelpRequest(
            title: resolvedQuery,
            context: "这题不硬选 · 等懂的人来一句"
        )
    }

    static func backendFallbackHelpRequest(for query: String) -> HelpRequest {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? defaultHelpRequest.title : query

        return HelpRequest(
            title: resolvedQuery,
            context: "现在还不够确定 · 发出去等懂的人来一句"
        )
    }
}

private func clean(_ value: String?, fallback: String) -> String {
    guard let value else { return fallback }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty ? fallback : trimmed
}

private func cleanArray(_ value: [String]?, fallback: [String]) -> [String] {
    guard let value else { return fallback }
    let cleaned = value
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
    return cleaned.isEmpty ? fallback : cleaned
}

private func cleanArrayAllowingEmpty(_ value: [String]?) -> [String] {
    guard let value else { return [] }
    return value
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
}

private func removeAskHuman(from values: [String]) -> [String] {
    values.filter { !$0.localizedCaseInsensitiveContains("问真人") }
}
